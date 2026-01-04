"""
Deep diagnostic for C2PA certificate issues.
"""

from pathlib import Path
from cryptography import x509
from cryptography.hazmat.primitives import serialization
import subprocess
import tempfile
import os

def analyze_cert(cert_path, key_path, label):
    """Analyze a certificate and key pair."""
    print(f"\n{'='*60}")
    print(f"ANALYZING: {label}")
    print(f"{'='*60}")
    
    # Check file existence
    if not cert_path.exists():
        print(f"ERROR: Certificate not found: {cert_path}")
        return False
    if not key_path.exists():
        print(f"ERROR: Private key not found: {key_path}")
        return False
    
    print(f"Cert: {cert_path}")
    print(f"Key:  {key_path}")
    
    # Load certificate
    cert_text = cert_path.read_text()
    cert_bytes = cert_path.read_bytes()
    
    # Count certificates in chain
    cert_count = cert_text.count("-----BEGIN CERTIFICATE-----")
    print(f"\nCertificate chain length: {cert_count} certificate(s)")
    
    # Parse each certificate
    pem_certs = []
    current = cert_bytes
    while b"-----BEGIN CERTIFICATE-----" in current:
        start = current.find(b"-----BEGIN CERTIFICATE-----")
        end = current.find(b"-----END CERTIFICATE-----") + len(b"-----END CERTIFICATE-----")
        pem_cert = current[start:end]
        pem_certs.append(pem_cert)
        current = current[end:]
    
    for i, pem_cert in enumerate(pem_certs):
        cert = x509.load_pem_x509_certificate(pem_cert)
        print(f"\n--- Certificate {i+1} ---")
        print(f"  Subject: {cert.subject.rfc4514_string()}")
        print(f"  Issuer:  {cert.issuer.rfc4514_string()}")
        print(f"  Serial:  {cert.serial_number}")
        print(f"  Valid From: {cert.not_valid_before_utc}")
        print(f"  Valid To:   {cert.not_valid_after_utc}")
        
        # Check if self-signed
        is_self_signed = cert.subject == cert.issuer
        print(f"  Self-Signed: {is_self_signed}")
        
        # Check extensions
        try:
            basic = cert.extensions.get_extension_for_class(x509.BasicConstraints)
            print(f"  CA: {basic.value.ca}")
        except x509.ExtensionNotFound:
            print(f"  CA: (no BasicConstraints extension)")
        
        try:
            key_usage = cert.extensions.get_extension_for_class(x509.KeyUsage)
            print(f"  Digital Signature: {key_usage.value.digital_signature}")
        except x509.ExtensionNotFound:
            print(f"  Key Usage: (not found)")
    
    # Load and check private key
    key_bytes = key_path.read_bytes()
    try:
        private_key = serialization.load_pem_private_key(key_bytes, password=None)
        print(f"\nPrivate Key: {type(private_key).__name__}")
        
        # Check if key matches first cert
        first_cert = x509.load_pem_x509_certificate(pem_certs[0])
        cert_public = first_cert.public_key()
        key_public = private_key.public_key()
        
        # Compare public keys
        cert_pub_bytes = cert_public.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        key_pub_bytes = key_public.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        
        keys_match = cert_pub_bytes == key_pub_bytes
        print(f"Key matches cert: {keys_match}")
        if not keys_match:
            print("  WARNING: Private key does NOT match the certificate!")
    except Exception as e:
        print(f"Private Key Error: {e}")
    
    return True


def test_signing(cert_path, key_path, label):
    """Actually test signing with c2pa."""
    print(f"\n{'='*60}")
    print(f"TEST SIGNING: {label}")
    print(f"{'='*60}")
    
    try:
        import c2pa
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import hashes
        import json
        import io
        
        # Load credentials
        key_bytes = key_path.read_bytes()
        private_key = serialization.load_pem_private_key(key_bytes, password=None)
        
        cert_text = cert_path.read_text()
        
        # Create signing callback
        def sign_callback(data):
            return private_key.sign(data, ec.ECDSA(hashes.SHA256()))
        
        # Create signer
        signer = c2pa.Signer.from_callback(
            callback=sign_callback,
            alg=c2pa.C2paSigningAlg.ES256,
            certs=cert_text,
            tsa_url="http://timestamp.digicert.com"
        )
        
        # Create a minimal test image (1x1 PNG)
        import struct
        import zlib
        
        def create_minimal_png():
            # Minimal 1x1 red PNG
            signature = b'\x89PNG\r\n\x1a\n'
            
            def png_chunk(chunk_type, data):
                chunk_len = struct.pack('>I', len(data))
                chunk_crc = struct.pack('>I', zlib.crc32(chunk_type + data) & 0xffffffff)
                return chunk_len + chunk_type + data + chunk_crc
            
            ihdr = struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)
            idat = zlib.compress(b'\x00\xff\x00\x00')  # 1 red pixel
            
            return signature + png_chunk(b'IHDR', ihdr) + png_chunk(b'IDAT', idat) + png_chunk(b'IEND', b'')
        
        png_data = create_minimal_png()
        
        # Build manifest
        manifest = {
            "claim_generator": "DiagnosticTest/1.0",
            "title": "Test Image",
            "assertions": []
        }
        
        builder = c2pa.Builder(json.dumps(manifest))
        
        source = io.BytesIO(png_data)
        dest = io.BytesIO()
        
        builder.sign(signer, "image/png", source, dest)
        
        result = dest.getvalue()
        print(f"SUCCESS! Signed image size: {len(result)} bytes")
        
        # Try to verify
        verify = io.BytesIO(result)
        reader = c2pa.Reader("image/png", verify)
        manifest_json = reader.json()
        print(f"Verification: OK")
        return True
        
    except Exception as e:
        print(f"FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    base = Path(__file__).parent
    
    # 1. Analyze persistent certs
    persistent_cert = base / "tools" / "c2pa" / "certificate.pem"
    persistent_key = base / "tools" / "c2pa" / "private_key.pem"
    
    if persistent_cert.exists() and persistent_key.exists():
        analyze_cert(persistent_cert, persistent_key, "Persistent Certificates")
        test_signing(persistent_cert, persistent_key, "Persistent Certificates")
    else:
        print("Persistent certificates not found")
    
    # 2. Analyze sample certs
    sample_cert = base / "tools" / "c2pa" / "c2patool" / "sample" / "es256_certs.pem"
    sample_key = base / "tools" / "c2pa" / "c2patool" / "sample" / "es256_private.key"
    
    if sample_cert.exists() and sample_key.exists():
        analyze_cert(sample_cert, sample_key, "Sample Certificates (c2patool)")
        test_signing(sample_cert, sample_key, "Sample Certificates (c2patool)")
    else:
        print("Sample certificates not found")
    
    print("\n" + "="*60)
    print("DIAGNOSIS COMPLETE")
    print("="*60)
