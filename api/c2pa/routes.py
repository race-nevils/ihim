from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from typing import Optional, Dict, Any
import tempfile
import os
import json
from pathlib import Path

router = APIRouter(prefix="/api/c2pa", tags=["C2PA"])


def _extract_manifest_data(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Extract structured data from C2PA manifest."""
    result = {
        "date_created": None,
        "author": None,
        "claim_generator": None,
        "cert_issuer": None,
        "format": None,
        "validation_status": None,
    }

    try:
        # Extract claim generator
        if "claim_generator" in manifest:
            result["claim_generator"] = manifest["claim_generator"]

        # Extract assertions
        if "assertions" in manifest:
            assertions = manifest["assertions"]

            # Look for creation date in various assertion types
            for assertion in assertions:
                if "label" in assertion:
                    label = assertion["label"]
                    data = assertion.get("data", {})

                    # Date created
                    if "stds.schema-org.CreativeWork" in label:
                        if "dateCreated" in data:
                            result["date_created"] = data["dateCreated"]
                        if "author" in data:
                            result["author"] = data["author"]

                    # Format information
                    if "c2pa.format" in label or "stds.exif" in label:
                        if "format" in data:
                            result["format"] = data["format"]

        # Extract signature info
        if "signature_info" in manifest:
            sig_info = manifest["signature_info"]

            # Timestamp
            if "time" in sig_info:
                result["date_created"] = sig_info["time"]

            # Certificate issuer
            if "issuer" in sig_info:
                result["cert_issuer"] = sig_info["issuer"]

        # Validation status
        if "validation_status" in manifest:
            status_list = manifest["validation_status"]
            if isinstance(status_list, list) and len(status_list) > 0:
                # Check if any validation failed
                has_error = any("error" in str(s).lower() for s in status_list)
                result["validation_status"] = "invalid" if has_error else "valid"
            else:
                result["validation_status"] = "valid"

    except Exception as e:
        # If extraction fails, return partial data
        pass

    return result


@router.post("/verify")
def verify_c2pa(
    image_url: Optional[str] = Form(None),
    image_file: Optional[UploadFile] = File(None)
):
    """
    Verify C2PA metadata from an image URL or uploaded file.
    Returns manifest data if C2PA exists.

    Parameters:
    - image_url: URL to download image from
    - image_file: Direct file upload

    One of image_url or image_file must be provided.
    """

    # Validate input
    if not image_url and not image_file:
        raise HTTPException(
            status_code=400,
            detail="Either image_url or image_file must be provided"
        )

    temp_file_path = None

    try:
        # Check if c2pa-python is available
        try:
            from c2pa import Reader
            c2pa_available = True
        except ImportError:
            c2pa_available = False

        if not c2pa_available:
            return {
                "success": False,
                "has_c2pa": False,
                "error": "c2pa-python library not installed",
                "message": "Install with: pip install c2pa-python"
            }

        # Create temp file
        suffix = ".jpg"  # Default
        if image_file:
            # Extract extension from uploaded file
            if image_file.filename:
                ext = os.path.splitext(image_file.filename)[1]
                if ext:
                    suffix = ext
        elif image_url:
            # Extract extension from URL
            ext = os.path.splitext(image_url)[1]
            if ext and ext.lower() in ['.jpg', '.jpeg', '.png', '.webp', '.gif']:
                suffix = ext

        # Create temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            temp_file_path = tmp.name

            if image_file:
                # Save uploaded file
                content = image_file.file.read()
                tmp.write(content)
            elif image_url:
                # Download from URL
                import httpx
                response = httpx.get(image_url, follow_redirects=True, timeout=30.0)
                response.raise_for_status()
                tmp.write(response.content)

        # Read C2PA manifest
        reader = Reader(temp_file_path)

        if not reader or not reader.get_active_manifest():
            # No C2PA data found
            return {
                "success": True,
                "has_c2pa": False,
                "message": "No C2PA manifest found in image"
            }

        # Extract manifest - get_active_manifest() returns the full manifest dict directly
        manifest_data = reader.get_active_manifest()

        # If manifest_data is None or empty, no C2PA found
        if not manifest_data:
            return {
                "success": True,
                "has_c2pa": False,
                "message": "No C2PA manifest found in image"
            }

        # Extract structured metadata
        structured = _extract_manifest_data(manifest_data)

        return {
            "success": True,
            "has_c2pa": True,
            "manifest": {
                **structured,
                "raw": manifest_data  # Full manifest for expandable view
            }
        }

    except HTTPException:
        # Re-raise HTTP exceptions
        raise

    except Exception as e:
        # Handle other errors
        error_msg = str(e)
        return {
            "success": False,
            "has_c2pa": False,
            "error": error_msg,
            "message": "Error processing image"
        }

    finally:
        # Clean up temp file
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.unlink(temp_file_path)
            except:
                pass  # Best effort cleanup


# Configuration
SIGNED_OUTPUT_DIR = Path("C:/Users/<user>/OneDrive/Pictures/Signed")
DEFAULT_CREATOR = "the operator James [scrubbed]"


def _get_test_signer():
    """Generate a test ES256 signer for local development.

    In production, this would use real certificates from a CA.
    For local use, we generate self-signed credentials with proper C2PA extensions.

    Returns:
        Tuple of (private_key_pem, cert_pem, alg) as bytes
    """
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography import x509
    from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
    from datetime import datetime, timedelta, timezone

    # Generate ECDSA P-256 key pair (ES256)
    private_key = ec.generate_private_key(ec.SECP256R1())

    # Create self-signed certificate with C2PA-compatible extensions
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Florida"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "Local"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "iHIM"),
        x509.NameAttribute(NameOID.COMMON_NAME, "iHIM C2PA Signer"),
    ])

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=365))
        # Add basic constraints (CA:FALSE for end-entity cert)
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True
        )
        # Add key usage for digital signatures
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=False,
                content_commitment=True,  # Non-repudiation
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False
            ),
            critical=True
        )
        # Add extended key usage
        .add_extension(
            x509.ExtendedKeyUsage([
                ExtendedKeyUsageOID.CODE_SIGNING,
                ExtendedKeyUsageOID.EMAIL_PROTECTION,
            ]),
            critical=False
        )
        .sign(private_key, hashes.SHA256())
    )

    # Serialize to PEM format (as bytes for c2pa ctypes)
    private_key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )

    cert_pem = cert.public_bytes(serialization.Encoding.PEM)

    return private_key_pem, cert_pem


@router.post("/sign")
def sign_image(
    image_file: UploadFile = File(...),
    creator: Optional[str] = Form(None),
    title: Optional[str] = Form(None),
    action: Optional[str] = Form("c2pa.created")
):
    """
    Sign an image with C2PA metadata and save to local Signed folder.

    Parameters:
    - image_file: Image to sign (required)
    - creator: Content creator name (default: the operator James [scrubbed])
    - title: Optional title for the content
    - action: C2PA action type (default: c2pa.created)

    Returns the path to the signed image.
    """
    temp_file_path = None

    try:
        # Check if c2pa-python is available
        try:
            from c2pa import Builder, Signer, C2paSignerInfo, C2paSigningAlg
            c2pa_available = True
        except ImportError as e:
            return {
                "success": False,
                "error": f"c2pa-python import error: {e}",
                "message": "Install with: pip install c2pa-python"
            }

        # Ensure output directory exists
        SIGNED_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        # Get file extension
        original_filename = image_file.filename or "image.jpg"
        ext = os.path.splitext(original_filename)[1].lower()
        if ext not in ['.jpg', '.jpeg', '.png', '.webp', '.gif', '.tiff', '.tif']:
            ext = '.jpg'

        # Generate output filename with timestamp
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = os.path.splitext(original_filename)[0]
        output_filename = f"{base_name}_signed_{timestamp}{ext}"
        output_path = SIGNED_OUTPUT_DIR / output_filename

        # Save uploaded file to temp location
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            temp_file_path = tmp.name
            content = image_file.file.read()
            tmp.write(content)

        # Build C2PA manifest
        manifest_json = {
            "claim_generator": "iHIM/1.0",
            "title": title or original_filename,
            "assertions": [
                {
                    "label": "stds.schema-org.CreativeWork",
                    "data": {
                        "@type": "CreativeWork",
                        "author": [
                            {
                                "@type": "Person",
                                "name": creator or DEFAULT_CREATOR
                            }
                        ],
                        "dateCreated": datetime.now().isoformat()
                    }
                },
                {
                    "label": "c2pa.actions",
                    "data": {
                        "actions": [
                            {
                                "action": action or "c2pa.created",
                                "when": datetime.now().isoformat(),
                                "softwareAgent": {
                                    "name": "iHIM Dashboard",
                                    "version": "1.0"
                                }
                            }
                        ]
                    }
                }
            ]
        }

        # Create builder
        builder = Builder(json.dumps(manifest_json))

        # Generate test signer credentials (returns bytes)
        private_key_pem, cert_pem = _get_test_signer()

        # Create signer info (ES256 = ECDSA with P-256)
        signer_info = C2paSignerInfo(
            alg=C2paSigningAlg.ES256,
            sign_cert=cert_pem,
            private_key=private_key_pem,
            ta_url=b""  # Empty bytes = no timestamp authority
        )

        # Create signer and sign the image
        with Signer.from_info(signer_info) as signer:
            # sign_file(source_path, dest_path, signer)
            result = builder.sign_file(
                temp_file_path,
                str(output_path),
                signer
            )

        return {
            "success": True,
            "message": "Image signed successfully",
            "output_path": str(output_path),
            "output_filename": output_filename,
            "creator": creator or DEFAULT_CREATOR,
            "manifest_bytes": len(result) if result else 0
        }

    except HTTPException:
        raise

    except Exception as e:
        import traceback
        error_msg = str(e)
        return {
            "success": False,
            "error": error_msg,
            "traceback": traceback.format_exc(),
            "message": "Error signing image"
        }

    finally:
        # Clean up temp file
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.unlink(temp_file_path)
            except:
                pass


@router.get("/signed-images")
def list_signed_images():
    """List all signed images in the output folder."""
    try:
        if not SIGNED_OUTPUT_DIR.exists():
            return {"success": True, "images": []}

        images = []
        for f in SIGNED_OUTPUT_DIR.iterdir():
            if f.is_file() and f.suffix.lower() in ['.jpg', '.jpeg', '.png', '.webp', '.gif', '.tiff', '.tif']:
                images.append({
                    "filename": f.name,
                    "path": str(f),
                    "size": f.stat().st_size,
                    "modified": f.stat().st_mtime
                })

        # Sort by modified time, newest first
        images.sort(key=lambda x: x["modified"], reverse=True)

        return {
            "success": True,
            "output_dir": str(SIGNED_OUTPUT_DIR),
            "images": images
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "images": []
        }


@router.get("/status")
def c2pa_status():
    """C2PA module status check."""
    return {
        "module": "c2pa",
        "status": "active",
        "output_dir": str(SIGNED_OUTPUT_DIR),
        "default_creator": DEFAULT_CREATOR,
        "features": ["verify", "sign", "list signed images"]
    }
