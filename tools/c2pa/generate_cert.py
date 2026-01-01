"""
Generate self-signed certificate for C2PA signing.
Run once to create your signing credentials.
"""

from cryptography import x509
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID, ObjectIdentifier
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from datetime import datetime, timedelta, timezone
import os

# C2PA-specific OID for document signing
# id-kp-documentSigning (1.3.6.1.5.5.7.3.36)
C2PA_DOCUMENT_SIGNING_OID = ObjectIdentifier("1.3.6.1.5.5.7.3.36")

# Output directory
CERT_DIR = os.path.dirname(os.path.abspath(__file__))

def generate_c2pa_certificate():
    """Generate EC P-256 key pair and self-signed certificate for C2PA."""

    # Generate private key (EC P-256 - required by C2PA)
    private_key = ec.generate_private_key(ec.SECP256R1())

    # Certificate subject/issuer
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "California"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "San Francisco"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "EdgeFlow AI"),
        x509.NameAttribute(NameOID.COMMON_NAME, "EdgeFlow AI C2PA Signer"),
    ])

    # Build certificate
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=365 * 5))  # 5 years
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=True,  # Non-repudiation
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([
                ExtendedKeyUsageOID.EMAIL_PROTECTION,  # S/MIME
                C2PA_DOCUMENT_SIGNING_OID,  # C2PA document signing
            ]),
            critical=False,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(private_key.public_key()),
            critical=False,
        )
        .sign(private_key, hashes.SHA256())
    )

    # Save private key (PKCS#8 PEM format)
    key_path = os.path.join(CERT_DIR, "private_key.pem")
    with open(key_path, "wb") as f:
        f.write(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        ))
    print(f"Private key saved: {key_path}")

    # Save certificate (PEM format)
    cert_path = os.path.join(CERT_DIR, "certificate.pem")
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    print(f"Certificate saved: {cert_path}")

    # Print certificate info
    print(f"\nCertificate Details:")
    print(f"  Subject: {cert.subject.rfc4514_string()}")
    print(f"  Valid from: {cert.not_valid_before_utc}")
    print(f"  Valid until: {cert.not_valid_after_utc}")
    print(f"  Serial: {cert.serial_number}")

    return key_path, cert_path

if __name__ == "__main__":
    generate_c2pa_certificate()
    print("\nCertificate generated! You can now sign images with C2PA.")
