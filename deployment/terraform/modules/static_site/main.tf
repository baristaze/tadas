# A static site in the cloud: built files in a private bucket, served by a
# CloudFront distribution at one domain name, under the security headers.
# Two sites use it. The portal (name "portal") calls the API cross-origin,
# routes client paths to index.html, and reads /config.json, written here per
# environment, so production serves the exact files staging already served.
# The company site (name "site") calls nothing, has one page and a 404 page,
# and carries its environment's links in its build.

locals {
  tags         = { "tadas:environment" = var.environment }
  s3_origin_id = var.name

  # A managed policy; the ID is fixed across accounts.
  caching_optimized = "658327ea-f89d-4fab-a63d-7e88639e58f6"

  # What the page may reach: its own origin, and, when given, the API over
  # HTTPS and over the websocket and the error reporter (the DSN is
  # scheme://key@host/project; only its origin is named). Nothing else, so a
  # script the site did not ship neither runs nor phones home. Neither build
  # has an inline script or style, so no unsafe directive is needed.
  api_origin    = trimsuffix(var.api_url, "/")
  api_origins   = var.api_url == "" ? [] : [local.api_origin, replace(local.api_origin, "/^http/", "ws")]
  sentry_origin = var.sentry_dsn == "" ? [] : [join("", regex("^(https?://)[^@/]+@([^/]+)", var.sentry_dsn))]
  connect_src   = concat(["'self'"], local.api_origins, local.sentry_origin)
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
  name                              = "tadas-${var.environment}-${var.name}"
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

# The runtime config a page fetches before it renders, when it has one (the
# portal). no-cache: a change reaches browsers on their next load without an
# invalidation.
resource "aws_s3_object" "config" {
  count = length(var.runtime_config) > 0 ? 1 : 0

  bucket        = aws_s3_bucket.this.id
  key           = "config.json"
  content_type  = "application/json"
  cache_control = "no-cache"
  content       = jsonencode(var.runtime_config)
}

moved {
  from = aws_s3_object.config
  to   = aws_s3_object.config[0]
}

# Client routes (/settings, ...) have no file; they get index.html. A path with
# a file extension is a real object and passes through. A site without client
# routes answers a missing path with its not-found page instead (below).
resource "aws_cloudfront_function" "spa_routes" {
  count = var.client_routes ? 1 : 0

  name    = "tadas-${var.environment}-${var.name}-routes"
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

moved {
  from = aws_cloudfront_function.spa_routes
  to   = aws_cloudfront_function.spa_routes[0]
}

resource "aws_cloudfront_response_headers_policy" "security" {
  name    = "tadas-${var.environment}-${var.name}-security"
  comment = "Security headers for the ${var.name}"

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
  comment             = "Tadas ${var.environment}: the ${var.name}"
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

  # Static files: cached at the edge; hashed assets never change, the entry
  # points and config.json revalidate (the deploy sets Cache-Control per file).
  default_cache_behavior {
    target_origin_id           = local.s3_origin_id
    allowed_methods            = ["GET", "HEAD", "OPTIONS"]
    cached_methods             = ["GET", "HEAD"]
    viewer_protocol_policy     = "redirect-to-https"
    compress                   = true
    cache_policy_id            = local.caching_optimized
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id

    dynamic "function_association" {
      for_each = aws_cloudfront_function.spa_routes
      content {
        event_type   = "viewer-request"
        function_arn = function_association.value.arn
      }
    }
  }

  # The bucket answers a missing key with 403, since the distribution may not
  # list it; both become the site's not-found page with a 404.
  dynamic "custom_error_response" {
    for_each = var.not_found_page == "" ? [] : [403, 404]
    content {
      error_code            = custom_error_response.value
      response_code         = 404
      response_page_path    = var.not_found_page
      error_caching_min_ttl = 60
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
