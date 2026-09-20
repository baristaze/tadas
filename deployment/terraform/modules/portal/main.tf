# The portal in the cloud: the built files in a private bucket, served by a
# CloudFront distribution at the app's domain name. The API has a domain of its
# own, which the portal calls cross-origin. The build carries no environment:
# every setting it needs is in /config.json, written here per environment, so
# production serves the exact files staging already served.

locals {
  tags         = { "tadas:environment" = var.environment }
  s3_origin_id = "portal"

  # A managed policy; the ID is fixed across accounts.
  caching_optimized = "658327ea-f89d-4fab-a63d-7e88639e58f6"

  # What the page may reach: its own origin, the API over HTTPS and over the
  # websocket, and the error reporter when one is configured (the DSN is
  # scheme://key@host/project; only its origin is named). Nothing else, so a
  # script the app did not ship neither runs nor phones home. The build has no
  # inline script or style, so no unsafe directive is needed.
  api_origin           = trimsuffix(var.api_url, "/")
  api_websocket_origin = replace(local.api_origin, "/^http/", "ws")
  sentry_origin        = var.sentry_dsn == "" ? [] : [join("", regex("^(https?://)[^@/]+@([^/]+)", var.sentry_dsn))]
  connect_src          = concat(["'self'", local.api_origin, local.api_websocket_origin], local.sentry_origin)
  content_security_policy = join("; ", [
    "default-src 'self'",
    "connect-src ${join(" ", local.connect_src)}",
    "img-src 'self' data:",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
  ])
}

resource "aws_s3_bucket" "this" {
  bucket = var.bucket_name
  # The nuke's apply turns this on first, so its destroy empties the build.
  force_destroy = var.destroyable
  tags          = local.tags
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
    apiUrl      = var.api_url
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

resource "aws_cloudfront_response_headers_policy" "security" {
  name    = "tadas-${var.environment}-portal-security"
  comment = "Security headers for the portal"

  security_headers_config {
    content_security_policy {
      content_security_policy = local.content_security_policy
      override                = true
    }

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
  comment             = "Tadas ${var.environment}: the portal"
  default_root_object = "index.html"
  http_version        = "http2and3"
  is_ipv6_enabled     = true
  price_class         = var.price_class
  aliases             = [var.domain_name]
  tags                = local.tags

  origin {
    origin_id                = local.s3_origin_id
    domain_name              = aws_s3_bucket.this.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.this.id
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

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = var.certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }
}
