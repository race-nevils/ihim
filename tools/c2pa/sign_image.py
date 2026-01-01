"""
C2PA Image Signing Tool for EdgeFlow AI

Usage:
    python sign_image.py input.png [output.png]

If output not specified, creates input_c2pa.png
"""

import c2pa
import sys
import os
import json
import io
from datetime import datetime, timezone

# Paths
TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
PRIVATE_KEY_PATH = os.path.join(TOOL_DIR, "private_key.pem")
CERT_PATH = os.path.join(TOOL_DIR, "certificate.pem")

def create_manifest(title: str = None, description: str = None) -> dict:
    """Create a C2PA manifest for EdgeFlow AI content."""
    return {
        "claim_generator": "EdgeFlowAI/1.0",
        "claim_generator_info": [
            {
                "name": "EdgeFlow AI",
                "version": "1.0.0"
            }
        ],
        "title": title or "EdgeFlow AI Content",
        "assertions": [
            {
                "label": "c2pa.actions",
                "data": {
                    "actions": [
                        {
                            "action": "c2pa.created",
                            "when": datetime.now(timezone.utc).isoformat(),
                            "softwareAgent": "EdgeFlow AI"
                        }
                    ]
                }
            },
            {
                "label": "c2pa.creative.work",
                "data": {
                    "author": [
                        {
                            "name": "EdgeFlow AI"
                        }
                    ],
                    "description": description or "Content created with EdgeFlow AI"
                }
            },
            {
                "label": "stds.schema-org.CreativeWork",
                "data": {
                    "@context": "https://schema.org",
                    "@type": "CreativeWork",
                    "author": [
                        {
                            "@type": "Organization",
                            "name": "EdgeFlow AI"
                        }
                    ]
                }
            }
        ]
    }


def sign_image(input_path: str, output_path: str = None, title: str = None, description: str = None):
    """Sign an image with C2PA manifest."""

    # Validate input exists
    if not os.path.exists(input_path):
        print(f"Error: Input file not found: {input_path}")
        sys.exit(1)

    # Check for credentials
    if not os.path.exists(PRIVATE_KEY_PATH) or not os.path.exists(CERT_PATH):
        print("Error: Certificate not found. Run generate_cert.py first.")
        sys.exit(1)

    # Default output path
    if not output_path:
        base, ext = os.path.splitext(input_path)
        output_path = f"{base}_c2pa{ext}"

    # Load credentials
    with open(PRIVATE_KEY_PATH, "rb") as f:
        private_key_pem = f.read()
    with open(CERT_PATH, "r") as f:
        certificate = f.read()

    # Load private key for signing
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import hashes

    private_key = serialization.load_pem_private_key(private_key_pem, password=None)

    # Create signing callback
    def sign_callback(data: bytes) -> bytes:
        """Sign data with ECDSA P-256 SHA-256."""
        signature = private_key.sign(data, ec.ECDSA(hashes.SHA256()))
        return signature

    # Create signer from callback
    signer = c2pa.Signer.from_callback(
        callback=sign_callback,
        alg=c2pa.C2paSigningAlg.ES256,
        certs=certificate,
        tsa_url="http://timestamp.digicert.com"
    )

    # Create manifest
    manifest_json = create_manifest(
        title=title or os.path.basename(input_path),
        description=description
    )

    # Build and sign
    builder = c2pa.Builder(manifest_json)

    # Determine MIME type from extension
    ext = os.path.splitext(input_path)[1].lower()
    mime_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
        ".avif": "image/avif",
        ".heic": "image/heic",
        ".heif": "image/heif",
    }
    mime_type = mime_types.get(ext, "application/octet-stream")

    # Read input file
    with open(input_path, "rb") as f:
        input_data = f.read()
    input_size = len(input_data)

    # Create stream objects for signing
    source_stream = io.BytesIO(input_data)
    dest_stream = io.BytesIO()

    # Sign the content
    builder.sign(signer, mime_type, source_stream, dest_stream)

    # Get the signed result
    result = dest_stream.getvalue()

    # Write output
    with open(output_path, "wb") as f:
        f.write(result)

    print(f"Signed: {input_path}")
    print(f"Output: {output_path}")
    print(f"Size: {input_size:,} -> {len(result):,} bytes")

    # Verify the signed file
    try:
        verify_stream = io.BytesIO(result)
        reader = c2pa.Reader(mime_type, verify_stream)
        manifest_store = json.loads(reader.json())
        active = manifest_store.get("active_manifest")
        if active:
            print(f"Manifest ID: {active}")
            print("C2PA signature verified!")
    except Exception as e:
        print(f"Warning: Could not verify: {e}")

    return output_path


def read_manifest(file_path: str):
    """Read and display C2PA manifest from a file."""
    if not os.path.exists(file_path):
        print(f"Error: File not found: {file_path}")
        sys.exit(1)

    ext = os.path.splitext(file_path)[1].lower()
    mime_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }
    mime_type = mime_types.get(ext, "image/png")

    with open(file_path, "rb") as f:
        data = f.read()

    try:
        stream = io.BytesIO(data)
        reader = c2pa.Reader(mime_type, stream)
        manifest_json = reader.json()
        manifest = json.loads(manifest_json)
        print(json.dumps(manifest, indent=2))
        return manifest
    except Exception as e:
        print(f"No C2PA manifest found or error reading: {e}")
        return None


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nCommands:")
        print("  python sign_image.py <input> [output]  - Sign an image")
        print("  python sign_image.py --read <file>     - Read manifest from image")
        sys.exit(0)

    if sys.argv[1] == "--read":
        if len(sys.argv) < 3:
            print("Error: Specify file to read")
            sys.exit(1)
        read_manifest(sys.argv[2])
    else:
        input_path = sys.argv[1]
        output_path = sys.argv[2] if len(sys.argv) > 2 else None
        sign_image(input_path, output_path)
