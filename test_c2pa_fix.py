"""
Quick test to verify C2PA signing fix is working.
This tests the credential loading logic outside of the full API.
"""

import sys
from pathlib import Path

# Add IHIM to path
sys.path.insert(0, str(Path(__file__).parent))

def test_load_credentials():
    """Test that we can load signing credentials."""
    print("Testing credential loading...")
    
    from cryptography.hazmat.primitives import serialization
    
    # Define paths to certificates
    cert_dir = Path(__file__).parent / "tools" / "c2pa"
    
    # Try persistent certificates first
    private_key_path = cert_dir / "private_key.pem"
    cert_path = cert_dir / "certificate.pem"
    
    # If persistent certs don't exist, try sample certs
    if not private_key_path.exists() or not cert_path.exists():
        print("✓ Persistent certs not found, falling back to sample certs...")
        private_key_path = cert_dir / "c2patool" / "sample" / "es256_private.key"
        cert_path = cert_dir / "c2patool" / "sample" / "es256_certs.pem"
    else:
        print("✓ Using persistent certificates")
    
    # Check if files exist
    if not private_key_path.exists():
        print(f"✗ ERROR: Private key not found at {private_key_path}")
        return False
    
    if not cert_path.exists():
        print(f"✗ ERROR: Certificate not found at {cert_path}")
        return False
    
    print(f"✓ Found private key: {private_key_path}")
    print(f"✓ Found certificate: {cert_path}")
    
    # Load the private key
    try:
        with open(private_key_path, "rb") as f:
            private_key_pem = f.read()
        
        private_key = serialization.load_pem_private_key(private_key_pem, password=None)
        print(f"✓ Loaded private key successfully (type: {type(private_key).__name__})")
    except Exception as e:
        print(f"✗ ERROR loading private key: {e}")
        return False
    
    # Load certificate chain as STRING (not bytes)
    try:
        with open(cert_path, "r") as f:
            cert_chain = f.read()
        
        print(f"✓ Loaded certificate chain successfully (type: {type(cert_chain).__name__}, length: {len(cert_chain)} chars)")
        
        # Verify it's a string
        if not isinstance(cert_chain, str):
            print(f"✗ ERROR: Certificate should be string, got {type(cert_chain)}")
            return False
        
        # Verify it looks like PEM
        if not cert_chain.strip().startswith("-----BEGIN"):
            print("✗ ERROR: Certificate doesn't look like PEM format")
            return False
        
        print("✓ Certificate is in PEM format (string)")
        
    except Exception as e:
        print(f"✗ ERROR loading certificate: {e}")
        return False
    
    return True


def test_signing_callback():
    """Test that we can create a signing callback."""
    print("\nTesting signing callback...")
    
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import hashes
        
        cert_dir = Path(__file__).parent / "tools" / "c2pa"
        private_key_path = cert_dir / "c2patool" / "sample" / "es256_private.key"
        
        # Load private key
        with open(private_key_path, "rb") as f:
            private_key_pem = f.read()
        
        private_key = serialization.load_pem_private_key(private_key_pem, password=None)
        
        # Create signing callback
        def sign_callback(data: bytes) -> bytes:
            """Sign data with ECDSA P-256 SHA-256."""
            signature = private_key.sign(data, ec.ECDSA(hashes.SHA256()))
            return signature
        
        # Test it
        test_data = b"test data to sign"
        signature = sign_callback(test_data)
        
        print(f"✓ Signing callback works (signature length: {len(signature)} bytes)")
        return True
        
    except Exception as e:
        print(f"✗ ERROR testing signing callback: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_c2pa_import():
    """Test that c2pa module is available."""
    print("\nTesting c2pa module import...")
    
    try:
        import c2pa
        print(f"✓ c2pa module imported successfully")
        
        # Check for key components
        if hasattr(c2pa, 'Signer'):
            print("✓ c2pa.Signer available")
        else:
            print("✗ c2pa.Signer not found")
            return False
        
        if hasattr(c2pa, 'Builder'):
            print("✓ c2pa.Builder available")
        else:
            print("✗ c2pa.Builder not found")
            return False
        
        if hasattr(c2pa, 'C2paSigningAlg'):
            print("✓ c2pa.C2paSigningAlg available")
        else:
            print("✗ c2pa.C2paSigningAlg not found")
            return False
        
        # Check for from_callback method
        if hasattr(c2pa.Signer, 'from_callback'):
            print("✓ c2pa.Signer.from_callback available")
        else:
            print("✗ c2pa.Signer.from_callback not found")
            return False
        
        return True
        
    except ImportError as e:
        print(f"✗ ERROR: c2pa module not available: {e}")
        print("  Install with: pip install c2pa-python")
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("C2PA Signing Fix - Validation Test")
    print("=" * 60)
    
    results = []
    
    # Test 1: Credentials
    results.append(("Load Credentials", test_load_credentials()))
    
    # Test 2: Signing callback
    results.append(("Signing Callback", test_signing_callback()))
    
    # Test 3: C2PA import
    results.append(("C2PA Module", test_c2pa_import()))
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    for test_name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status}: {test_name}")
    
    all_passed = all(passed for _, passed in results)
    
    print("\n" + "=" * 60)
    if all_passed:
        print("✓ ALL TESTS PASSED - Ready to test signing!")
        print("\nNext steps:")
        print("1. Test signing through the iHIM UI")
        print("2. Verify with: IHIM/tools/c2pa/c2patool/c2patool.exe verify <signed_image>")
        print("3. Upload to https://contentcredentials.org/verify")
    else:
        print("✗ SOME TESTS FAILED - Fix issues before testing")
    print("=" * 60)
    
    sys.exit(0 if all_passed else 1)
