# One private, versioned, encrypted bucket per enum member. Tenant isolation
# is the impl's key prefix; nothing here is public.

locals {
  tags = { "tadas:environment" = var.environment }
}

resource "aws_s3_bucket" "this" {
  for_each = toset(var.buckets)

  bucket = "${var.prefix}-${each.key}"
  # A destroy of a bucket with objects in it fails, which is right until the
  # nuke; the nuke's apply turns this on first, so its destroy empties them.
  force_destroy = var.destroyable
  tags          = local.tags
}

resource "aws_s3_bucket_public_access_block" "this" {
  for_each = aws_s3_bucket.this

  bucket                  = each.value.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "this" {
  for_each = aws_s3_bucket.this

  bucket = each.value.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  for_each = aws_s3_bucket.this

  bucket = each.value.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

data "aws_iam_policy_document" "use" {
  statement {
    actions   = ["s3:ListBucket"]
    resources = [for bucket in aws_s3_bucket.this : bucket.arn]
  }

  statement {
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = [for bucket in aws_s3_bucket.this : "${bucket.arn}/*"]
  }
}

resource "aws_iam_policy" "use" {
  name   = "tadas-${var.environment}-buckets"
  policy = data.aws_iam_policy_document.use.json
  tags   = local.tags
}
