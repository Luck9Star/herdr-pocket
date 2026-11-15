package fixture

import (
	"bytes"
	"crypto/x509"
	"testing"
)

func TestCertificateIssuerKeyIdentifiers(t *testing.T) {
	cert, _ := certificate(t)
	if len(cert.Certificate) != 2 {
		t.Fatal("expected leaf and issuer chain")
	}
	leaf, err := x509.ParseCertificate(cert.Certificate[0])
	if err != nil {
		t.Fatal("invalid fixture leaf")
	}
	issuer, err := x509.ParseCertificate(cert.Certificate[1])
	if err != nil {
		t.Fatal("invalid fixture issuer")
	}
	if len(issuer.SubjectKeyId) == 0 || !bytes.Equal(leaf.AuthorityKeyId, issuer.SubjectKeyId) {
		t.Fatal("fixture leaf AKI does not match actual issuer SKI")
	}
	roots := x509.NewCertPool()
	roots.AddCert(issuer)
	if _, err := leaf.Verify(x509.VerifyOptions{Roots: roots, DNSName: "127.0.0.1"}); err != nil {
		t.Fatal("fixture certificate chain failed normal verification")
	}
}
