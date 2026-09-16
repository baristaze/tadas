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
