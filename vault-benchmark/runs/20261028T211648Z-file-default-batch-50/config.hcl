duration        = "60s"
report_mode     = "terse"
random_mounts   = false
cleanup         = false
disable_http2   = true
workers         = 10

test "transit_encrypt" "batch_encrypt" {
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
      batch_input = [
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDAwMQ==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDAwMg==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDAwMw==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDAwNA==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDAwNQ==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDAwNg==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDAwNw==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDAwOA==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDAwOQ==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDAxMA==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDAxMQ==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDAxMg==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDAxMw==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDAxNA==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDAxNQ==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDAxNg==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDAxNw==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDAxOA==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDAxOQ==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDAyMA==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDAyMQ==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDAyMg==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDAyMw==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDAyNA==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDAyNQ==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDAyNg==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDAyNw==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDAyOA==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDAyOQ==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDAzMA==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDAzMQ==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDAzMg==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDAzMw==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDAzNA==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDAzNQ==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDAzNg==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDAzNw==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDAzOA==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDAzOQ==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA0MA==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA0MQ==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA0Mg==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA0Mw==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA0NA==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA0NQ==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA0Ng==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA0Nw==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA0OA==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA0OQ==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA1MA==" }
      ]
    }
  }
}

test "transit_decrypt" "batch_decrypt" {
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
