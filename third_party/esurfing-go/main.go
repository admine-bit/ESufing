package main

import (
    "bufio"
    "encoding/json"
    "fmt"
    "os"

    "esurfingcrypto/cipher"
)

type request struct {
    Operation string `json:"operation"`
    Algorithm string `json:"algorithm"`
    Data string `json:"data"`
}

func handle(req request) (result map[string]string) {
    // Treat malformed ciphertext as an error without printing request contents.
    defer func() {
        if recover() != nil { result = map[string]string{"error": "invalid cipher input"} }
    }()
    impl, err := cipher.NewCipher(req.Algorithm)
    if err != nil { return map[string]string{"error": "unsupported algorithm"} }
    switch req.Operation {
    case "encrypt":
        return map[string]string{"data": impl.Encrypt(req.Data)}
    case "decrypt":
        return map[string]string{"data": impl.Decrypt(req.Data)}
    default:
        return map[string]string{"error": "unsupported operation"}
    }
}

func main() {
    scanner := bufio.NewScanner(os.Stdin)
    scanner.Buffer(make([]byte, 4096), 2*1024*1024)
    encoder := json.NewEncoder(os.Stdout)
    for scanner.Scan() {
        var req request
        if json.Unmarshal(scanner.Bytes(), &req) != nil {
            _ = encoder.Encode(map[string]string{"error": "invalid request"})
            continue
        }
        _ = encoder.Encode(handle(req))
    }
    if scanner.Err() != nil {
        fmt.Fprintln(os.Stderr, "crypto input read failed")
        os.Exit(1)
    }
}
