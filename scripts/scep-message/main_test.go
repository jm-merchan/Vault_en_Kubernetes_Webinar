package main

import (
	"crypto/x509"
	"encoding/asn1"
	"testing"
)

func TestHasChallenge(t *testing.T) {
	attribute := func(oid asn1.ObjectIdentifier, value string) asn1.RawValue {
		t.Helper()
		encoded, err := asn1.Marshal(struct {
			Type   asn1.ObjectIdentifier
			Values []string `asn1:"set"`
		}{oid, []string{value}})
		if err != nil {
			t.Fatal(err)
		}
		return asn1.RawValue{FullBytes: encoded}
	}
	challenge := asn1.ObjectIdentifier{1, 2, 840, 113549, 1, 9, 7}
	extension := asn1.ObjectIdentifier{1, 2, 840, 113549, 1, 9, 14}
	for _, tc := range []struct {
		name       string
		attributes []asn1.RawValue
		want       bool
	}{
		{"no attributes", nil, false},
		{"non-challenge attribute", []asn1.RawValue{attribute(extension, "test")}, false},
		{"challenge string", []asn1.RawValue{attribute(challenge, "test-only")}, true},
		{"empty challenge still present", []asn1.RawValue{attribute(challenge, "")}, true},
		{"challenge after another attribute", []asn1.RawValue{attribute(extension, "test"), attribute(challenge, "test-only")}, true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			der, err := asn1.Marshal(struct {
				Version    int
				Subject    asn1.RawValue
				PublicKey  asn1.RawValue
				Attributes []asn1.RawValue `asn1:"tag:0"`
			}{0, asn1.RawValue{FullBytes: []byte{0x30, 0}}, asn1.RawValue{FullBytes: []byte{0x30, 0}}, tc.attributes})
			if err != nil {
				t.Fatal(err)
			}
			if got := hasChallenge(&x509.CertificateRequest{RawTBSCertificateRequest: der}); got != tc.want {
				t.Fatalf("hasChallenge() = %v, want %v", got, tc.want)
			}
		})
	}
}
