# The portal in the cloud: the built files in a private bucket, served by one
# CloudFront distribution that also fronts the API. The browser sees a single
# HTTPS origin, so the portal calls the API with relative URLs, needs no CORS,
# and opens its realtime socket on the same host. The build carries no
# environment: every setting it needs is in /config.json, written here per
# environment, so production serves the exact files dev already served.

locals {
  tags         = { "tadas:environment" = var.environment }
  s3_origin_id = "portal"
  api_origin   = "api"

  # Managed policies (the IDs are fixed across accounts).
  caching_optimized = "658327ea-f89d-4fab-a63d-7e88639e58f6"
  all_viewer        = "216adef6-5c7f-47e4-b989-5492eafa07d3"
}

resource "aws_s3_bucket" "this" {
  bucket = var.bucket_name
  tags   = local.tags
}

resource "aws_s3_bucket_public_access_block" "this" {
  bucket                  = aws_s3_bucket.this.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "this" {
  bucket = aws_s3_bucket.this.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  bucket = aws_s3_bucket.this.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Only this distribution reads the bucket, signing each request (OAC).
resource "aws_cloudfront_origin_access_control" "this" {
  name                              = "tadas-${var.environment}-portal"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

data "aws_iam_policy_document" "read_from_cloudfront" {
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.this.arn}/*"]

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.this.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "this" {
  bucket = aws_s3_bucket.this.id
  policy = data.aws_iam_policy_document.read_from_cloudfront.json
}

# The runtime config the portal fetches before it renders. no-cache: a change
# reaches browsers on their next load without an invalidation.
resource "aws_s3_object" "config" {
  bucket        = aws_s3_bucket.this.id
  key           = "config.json"
  content_type  = "application/json"
  cache_control = "no-cache"
  content = jsonencode({
    apiUrl      = ""
    sentryDsn   = var.sentry_dsn
    environment = var.environment
  })
}

# Client routes (/settings, ...) have no file; they get index.html. A path with
# a file extension is a real object and passes through.
resource "aws_cloudfront_function" "spa_routes" {
  name    = "tadas-${var.environment}-portal-routes"
  runtime = "cloudfront-js-2.0"
  comment = "Serves index.html for client-side routes"
  publish = true
  code    = <<-JS
    function handler(event) {
      var request = event.request;
      var last = request.uri.split("/").pop();
      if (last.indexOf(".") === -1) {
        request.uri = "/index.html";
      }
      return request;
    }
  JS
}

# The API is never cached, but GET requests still need their bearer token:
# CloudFront forwards Authorization on GET only when the cache policy names it,
# and naming a header needs a maximum TTL above zero. The API sends no
# Cache-Control, so the default TTL of zero keeps every response uncached.
resource "aws_cloudfront_cache_policy" "api" {
  name        = "tadas-${var.environment}-api"
  comment     = "Uncached API responses, keyed on the bearer token"
  min_ttl     = 0
  default_ttl = 0
  max_ttl     = 1

  parameters_in_cache_key_and_forwarded_to_origin {
    enable_accept_encoding_brotli = false
    enable_accept_encoding_gzip   = false

    headers_config {
      header_behavior = "whitelist"
      headers {
        items = ["Authorization"]
      }
    }

    cookies_config {
      cookie_behavior = "none"
    }

    query_strings_config {
      query_string_behavior = "all"
    }
  }
}

resource "aws_cloudfront_response_headers_policy" "security" {
  name    = "tadas-${var.environment}-portal-security"
  comment = "Security headers for the portal and the API"

  security_headers_config {
    content_type_options {
      override = true
    }

    frame_options {
      frame_option = "DENY"
      override     = true
    }

    referrer_policy {
      referrer_policy = "strict-origin-when-cross-origin"
      override        = true
    }

    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = true
      override                   = true
    }
  }
}

resource "aws_cloudfront_distribution" "this" {
  enabled             = true
  comment             = "Tadas ${var.environment}: the portal and the API behind it"
  default_root_object = "index.html"
  http_version        = "http2and3"
  is_ipv6_enabled     = true
  price_class         = var.price_class
  aliases             = var.aliases
  tags                = local.tags

  origin {
    origin_id                = local.s3_origin_id
    domain_name              = aws_s3_bucket.this.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.this.id
  }

  origin {
    origin_id   = local.api_origin
    domain_name = var.api_origin_domain

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = var.api_origin_https ? "https-only" : "http-only"
      origin_ssl_protocols   = ["TLSv1.2"]
      # Longer than the load balancer's idle timeout is pointless; this matches it.
      origin_read_timeout      = 60
      origin_keepalive_timeout = 60
    }
  }

  # Static files: cached at the edge; hashed assets never change, index.html
  # and config.json revalidate (the deploy sets Cache-Control per file).
  default_cache_behavior {
    target_origin_id           = local.s3_origin_id
    allowed_methods            = ["GET", "HEAD", "OPTIONS"]
    cached_methods             = ["GET", "HEAD"]
    viewer_protocol_policy     = "redirect-to-https"
    compress                   = true
    cache_policy_id            = local.caching_optimized
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.spa_routes.arn
    }
  }

  # The API, including the realtime WebSocket at /v1/realtime (which needs the
  # viewer's headers forwarded).
  ordered_cache_behavior {
    path_pattern               = "/v1/*"
    target_origin_id           = local.api_origin
    allowed_methods            = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods             = ["GET", "HEAD"]
    viewer_protocol_policy     = "https-only"
    compress                   = true
    cache_policy_id            = aws_cloudfront_cache_policy.api.id
    origin_request_policy_id   = local.all_viewer
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = var.certificate_arn == null
    acm_certificate_arn            = var.certificate_arn
    ssl_support_method             = var.certificate_arn == null ? null : "sni-only"
    minimum_protocol_version       = var.certificate_arn == null ? "TLSv1" : "TLSv1.2_2021"
  }
}
