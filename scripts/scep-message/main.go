// scep-message builds and verifies RFC 8894 messages; curl handles HTTP.
// This lab helper deliberately supports only RSA, SHA-256 and AES-256-CBC.
package main

import (
	"bytes"
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha256"
	"crypto/x509"
	"encoding/asn1"
	"encoding/hex"
	"encoding/json"
	"encoding/pem"
	"errors"
	"flag"
	"fmt"
	"os"
	"slices"

	"github.com/smallstep/pkcs7"
)

func oid(n int) asn1.ObjectIdentifier { return asn1.ObjectIdentifier{2, 16, 840, 1, 113733, 1, 9, n} }
func must[T any](v T, err error) T {
	if err != nil {
		panic(err)
	}
	return v
}
func check(err error) {
	if err != nil {
		panic(err)
	}
}
func require(ok bool, msg string) {
	if !ok {
		panic(errors.New(msg))
	}
}
func readPEM(path, kind string) []byte {
	b, _ := pem.Decode(must(os.ReadFile(path)))
	require(b != nil, "missing PEM block: "+path)
	require(b.Type == kind, "unexpected PEM type: "+path)
	return b.Bytes
}
func readKey(path string) *rsa.PrivateKey {
	b, _ := pem.Decode(must(os.ReadFile(path)))
	require(b != nil, "missing private-key PEM")
	if b.Type == "RSA PRIVATE KEY" {
		return must(x509.ParsePKCS1PrivateKey(b.Bytes))
	}
	k := must(x509.ParsePKCS8PrivateKey(b.Bytes))
	r, ok := k.(*rsa.PrivateKey)
	require(ok, "RSA key required")
	return r
}
func output(v any) { check(json.NewEncoder(os.Stdout).Encode(v)) }

// Parse raw PKCS#10 attributes: crypto/x509's Attributes representation can
// omit a challengePassword encoded as SET OF PrintableString by OpenSSL.
// Only expose presence, never the challenge value.
func hasChallenge(csr *x509.CertificateRequest) bool {
	var request struct {
		Version    int
		Subject    asn1.RawValue
		PublicKey  asn1.RawValue
		Attributes []asn1.RawValue `asn1:"tag:0"`
	}
	rest, err := asn1.Unmarshal(csr.RawTBSCertificateRequest, &request)
	check(err)
	require(len(rest) == 0, "trailing CSR request data")
	for _, raw := range request.Attributes {
		var attribute struct {
			Type   asn1.ObjectIdentifier
			Values asn1.RawValue
		}
		_, err := asn1.Unmarshal(raw.FullBytes, &attribute)
		check(err)
		if attribute.Type.Equal(asn1.ObjectIdentifier{1, 2, 840, 113549, 1, 9, 7}) {
			return true
		}
	}
	return false
}

func run() {
	require(len(os.Args) > 1, "usage: scep-message prepare|verify [flags]")
	f := flag.NewFlagSet(os.Args[1], flag.ExitOnError)
	csrPath := f.String("csr", "", "PEM CSR")
	certPath := f.String("signer-cert", "", "self-signed or current certificate")
	keyPath := f.String("signer-key", "", "RSA signer key")
	caPath := f.String("ca", "", "pinned issuing CA, PEM")
	reqPath := f.String("request", "", "request DER")
	respPath := f.String("response", "", "response DER")
	outPath := f.String("out", "", "output DER (prepare) or PEM certificate (verify)")
	msgType := f.String("type", "19", "19=PKCSReq, 17=RenewalReq")
	check(f.Parse(os.Args[2:]))
	ca := must(x509.ParseCertificate(readPEM(*caPath, "CERTIFICATE")))
	signer := must(x509.ParseCertificate(readPEM(*certPath, "CERTIFICATE")))
	key := readKey(*keyPath)
	require(bytes.Equal(must(x509.MarshalPKIXPublicKey(&key.PublicKey)), must(x509.MarshalPKIXPublicKey(signer.PublicKey))), "signer certificate/key mismatch")
	csr := must(x509.ParseCertificateRequest(readPEM(*csrPath, "CERTIFICATE REQUEST")))
	check(csr.CheckSignature())
	switch os.Args[1] {
	case "prepare":
		require(*msgType == "19" || *msgType == "17", "unsupported message type")
		pkcs7.ContentEncryptionAlgorithm = pkcs7.EncryptionAlgorithmAES256CBC
		envelope := must(pkcs7.Encrypt(csr.Raw, []*x509.Certificate{ca}))
		sd := must(pkcs7.NewSignedData(envelope))
		sd.SetDigestAlgorithm(pkcs7.OIDDigestAlgorithmSHA256)
		hash := sha256.Sum256(csr.RawSubjectPublicKeyInfo)
		transaction := hex.EncodeToString(hash[:])
		nonce := make([]byte, 16)
		_, err := rand.Read(nonce)
		check(err)
		check(sd.AddSigner(signer, key, pkcs7.SignerInfoConfig{ExtraSignedAttributes: []pkcs7.Attribute{
			{Type: oid(7), Value: transaction},
			{Type: oid(2), Value: *msgType},
			{Type: oid(5), Value: nonce},
		}}))
		check(os.WriteFile(*outPath, must(sd.Finish()), 0600))
		output(map[string]any{"message_type": *msgType, "transaction_id": transaction, "signer_cn": signer.Subject.CommonName, "csr_cn": csr.Subject.CommonName, "challenge_present": hasChallenge(csr), "encryption": "AES-256-CBC", "digest": "SHA-256"})
	case "verify":
		req := must(pkcs7.Parse(must(os.ReadFile(*reqPath))))
		check(req.Verify())
		resp := must(pkcs7.Parse(must(os.ReadFile(*respPath))))
		check(resp.Verify())
		responseSigner := resp.GetOnlySigner()
		require(responseSigner != nil && bytes.Equal(responseSigner.Raw, ca.Raw), "response not signed by pinned CA")
		var requestID, responseID, responseType, status string
		var senderNonce, recipientNonce []byte
		check(req.UnmarshalSignedAttribute(oid(7), &requestID))
		check(req.UnmarshalSignedAttribute(oid(5), &senderNonce))
		check(resp.UnmarshalSignedAttribute(oid(7), &responseID))
		check(resp.UnmarshalSignedAttribute(oid(6), &recipientNonce))
		check(resp.UnmarshalSignedAttribute(oid(2), &responseType))
		check(resp.UnmarshalSignedAttribute(oid(3), &status))
		require(responseType == "3", "expected CertRep (3)")
		require(requestID == responseID, "transaction ID mismatch")
		require(bytes.Equal(senderNonce, recipientNonce), "nonce mismatch")
		if status != "0" {
			var failInfo string
			_ = resp.UnmarshalSignedAttribute(oid(4), &failInfo)
			output(map[string]any{"pki_status": status, "fail_info": failInfo, "signature_verified": true, "transaction_id": responseID})
			os.Exit(2)
		}
		envelope := must(pkcs7.Parse(resp.Content))
		bundle := must(pkcs7.Parse(must(envelope.Decrypt(signer, key))))
		var issued *x509.Certificate
		for _, c := range bundle.Certificates {
			if !c.IsCA && bytes.Equal(c.RawSubjectPublicKeyInfo, csr.RawSubjectPublicKeyInfo) {
				require(issued == nil, "multiple matching leaf certificates")
				issued = c
			}
		}
		require(issued != nil, "response has no leaf matching CSR public key")
		check(issued.CheckSignatureFrom(ca))
		require(issued.Subject.CommonName == csr.Subject.CommonName, "issued CN differs from CSR")
		require(slices.Equal(issued.DNSNames, csr.DNSNames), "issued DNS SANs differ from CSR")
		check(os.WriteFile(*outPath, pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: issued.Raw}), 0600))
		hash := sha256.Sum256(issued.Raw)
		output(map[string]any{"pki_status": status, "signature_verified": true, "nonce_verified": true, "transaction_id": responseID, "common_name": issued.Subject.CommonName, "serial": fmt.Sprintf("%X", issued.SerialNumber), "sha256": hex.EncodeToString(hash[:])})
	default:
		panic(errors.New("unknown subcommand"))
	}
}

func main() {
	defer func() {
		if e := recover(); e != nil {
			fmt.Fprintln(os.Stderr, e)
			os.Exit(1)
		}
	}()
	run()
}
