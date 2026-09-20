terraform {
  required_version = ">= 1.10" # the S3 backend's use_lockfile

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Partial configuration: bucket, key, and region arrive as -backend-config
  # arguments (see ../../modules/README.md). CI validates with -backend=false.
  backend "s3" {}
}

provider "aws" {
  region = var.region

  default_tags {
    tags = { "tadas:managed-by" = "terraform" }
  }
}

# CloudFront reads certificates from us-east-1 only, whatever var.region is.
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"

  default_tags {
    tags = { "tadas:managed-by" = "terraform" }
  }
}
