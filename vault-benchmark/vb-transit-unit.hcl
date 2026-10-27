duration        = "60s"
report_mode     = "terse"
random_mounts   = false
cleanup         = false
disable_http2   = true
workers         = 50

test "transit_encrypt" "unit_encrypt" {
  mount_name = "transit"
  weight = 95
  config {
    use_existing_mount = true
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
  mount_name = "transit"
  weight = 5
  config {
    use_existing_mount = true
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
