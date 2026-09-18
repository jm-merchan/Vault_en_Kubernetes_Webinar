duration        = "60s"
report_mode     = "terse"
random_mounts   = true
cleanup         = true
disable_http2   = false
workers         = 10

test "transit_encrypt" "unit_encrypt" {
  weight = 95
  config {
    payload_len = 19
    keys {
      name = "orders"
      type = "aes256-gcm96"
    }
    encrypt {
      name = "orders"
    }
  }
}

test "transit_decrypt" "unit_decrypt" {
  weight = 5
  config {
    payload_len = 19
    keys {
      name = "orders"
      type = "aes256-gcm96"
    }
    decrypt {
      name = "orders"
    }
  }
}
