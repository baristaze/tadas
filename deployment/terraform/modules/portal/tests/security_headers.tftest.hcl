# The Content-Security-Policy the distribution sends: the page's own origin,
# the API over HTTPS and over the websocket, the error reporter when one is
# configured, and nothing else. Runs offline: `terraform test` in this folder.

mock_provider "aws" {}

variables {
  environment     = "test"
  bucket_name     = "tadas-test-portal"
  domain_name     = "app.example.test"
  certificate_arn = "arn:aws:acm:us-east-1:123456789012:certificate/test"
  api_url         = "https://api.example.test"
}

run "names_the_page_and_the_api_and_nothing_else" {
  command = plan

  assert {
    condition     = aws_cloudfront_response_headers_policy.security.security_headers_config[0].content_security_policy[0].content_security_policy == "default-src 'self'; connect-src 'self' https://api.example.test wss://api.example.test; img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    error_message = "the policy names something other than the page and the API, or misses one of them"
  }

  assert {
    condition     = aws_cloudfront_response_headers_policy.security.security_headers_config[0].content_security_policy[0].override == true
    error_message = "the policy must replace whatever the origin sends"
  }
}

run "strips_a_trailing_slash_from_the_api_url" {
  command = plan

  variables {
    api_url = "https://api.example.test/"
  }

  assert {
    condition     = strcontains(aws_cloudfront_response_headers_policy.security.security_headers_config[0].content_security_policy[0].content_security_policy, "connect-src 'self' https://api.example.test wss://api.example.test;")
    error_message = "a trailing slash would make the origin a path and the source useless"
  }
}

run "names_the_error_reporter_when_one_is_configured" {
  command = plan

  variables {
    sentry_dsn = "https://0123456789abcdef@errors.example.test/7"
  }

  assert {
    condition     = strcontains(aws_cloudfront_response_headers_policy.security.security_headers_config[0].content_security_policy[0].content_security_policy, "connect-src 'self' https://api.example.test wss://api.example.test https://errors.example.test;")
    error_message = "the error reporter's origin, and only its origin, joins connect-src"
  }
}

run "refuses_a_dsn_that_is_not_one" {
  command = plan

  variables {
    sentry_dsn = "errors.example.test"
  }

  expect_failures = [var.sentry_dsn]
}
