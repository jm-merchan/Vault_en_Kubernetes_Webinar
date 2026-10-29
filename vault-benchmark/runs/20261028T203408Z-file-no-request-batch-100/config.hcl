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
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA1MA==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA1MQ==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA1Mg==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA1Mw==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA1NA==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA1NQ==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA1Ng==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA1Nw==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA1OA==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA1OQ==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA2MA==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA2MQ==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA2Mg==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA2Mw==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA2NA==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA2NQ==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA2Ng==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA2Nw==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA2OA==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA2OQ==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA3MA==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA3MQ==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA3Mg==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA3Mw==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA3NA==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA3NQ==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA3Ng==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA3Nw==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA3OA==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA3OQ==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA4MA==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA4MQ==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA4Mg==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA4Mw==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA4NA==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA4NQ==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA4Ng==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA4Nw==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA4OA==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA4OQ==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA5MA==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA5MQ==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA5Mg==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA5Mw==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA5NA==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA5NQ==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA5Ng==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA5Nw==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA5OA==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDA5OQ==" },
        { plaintext = "NDAwMCAwMDAwIDAwMDAgMDEwMA==" }
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
