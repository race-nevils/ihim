from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse

from typing import Optional, Dict, Any
import tempfile
import os
import json
from pathlib import Path

router = APIRouter(prefix="/api/c2pa", tags=["C2PA"])


def _extract_manifest_data(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Extract structured data from C2PA manifest - comprehensive extraction."""
    result = {
        # Basic Info
        "title": None,
        "date_created": None,
        "author": None,
        "creator": None,
        
        # Claim Info
        "claim_generator": None,
        "claim_generator_info": None,
        "active_manifest": None,
        
        # AI & Software Assertions
        "assertion": None,
        "software_agent": None,
        "software_agent_version": None,
        "action": None,
        
        # Relationships
        "relationship": None,
        
        # Cryptographic Details
        "hash_algorithm": None,
        "pad": None,
        "alg": None,
        "ta": None,
        "tst": None,
        "cert_issuer": None,
        
        # File Info
        "format": None,
        "file_name": None,
        "file_size": None,
        "file_type": None,
        
        # Validation
        "validation_status": None,
    }

    try:
        # Extract title
        if "title" in manifest:
            result["title"] = manifest["title"]
        
        # Extract claim generator
        if "claim_generator" in manifest:
            cg = manifest["claim_generator"]
            result["claim_generator"] = cg
            # Try to extract version from claim_generator string (e.g., "Lightroom/6.5")
            if isinstance(cg, str) and "/" in cg:
                parts = cg.split("/", 1)
                result["claim_generator"] = parts[0]
                if len(parts) > 1:
                    result["claim_generator_info"] = parts[1]
        
        # Extract active manifest label
        if "label" in manifest:
            result["active_manifest"] = manifest["label"]
        
        # Extract format
        if "format" in manifest:
            result["format"] = manifest["format"]
            result["file_type"] = manifest["format"]
        
        # Extract instance_id for file info
        if "instance_id" in manifest:
            result["file_name"] = manifest["instance_id"]

        # Extract assertions
        if "assertions" in manifest:
            assertions = manifest["assertions"]

            for assertion in assertions:
                if not isinstance(assertion, dict):
                    continue
                    
                label = assertion.get("label", "")
                data = assertion.get("data", {})

                # Store assertion type
                if label and not result["assertion"]:
                    result["assertion"] = label

                # Creative Work assertion
                if "stds.schema-org.CreativeWork" in label:
                    if isinstance(data, dict):
                        if "dateCreated" in data:
                            result["date_created"] = data["dateCreated"]
                        if "author" in data:
                            author = data["author"]
                            if isinstance(author, list) and len(author) > 0:
                                first_author = author[0]
                                if isinstance(first_author, dict):
                                    result["author"] = first_author.get("name", str(first_author))
                                    result["creator"] = first_author.get("name", str(first_author))
                                else:
                                    result["author"] = str(first_author)
                                    result["creator"] = str(first_author)
                            else:
                                result["author"] = str(author)
                                result["creator"] = str(author)

                # Actions assertion
                if "c2pa.actions" in label:
                    if isinstance(data, dict) and "actions" in data:
                        actions = data["actions"]
                        if isinstance(actions, list) and len(actions) > 0:
                            first_action = actions[0]
                            if isinstance(first_action, dict):
                                result["action"] = first_action.get("action")
                                
                                # Extract software agent
                                agent = first_action.get("softwareAgent", {})
                                if isinstance(agent, dict):
                                    result["software_agent"] = agent.get("name")
                                    result["software_agent_version"] = agent.get("version")
                                elif isinstance(agent, str):
                                    result["software_agent"] = agent
                
                # AI assertions
                if "c2pa.ai" in label or "ai.generative" in label:
                    result["assertion"] = label
                    if isinstance(data, dict):
                        if "softwareAgent" in data:
                            agent = data["softwareAgent"]
                            if isinstance(agent, dict):
                                result["software_agent"] = agent.get("name")
                                result["software_agent_version"] = agent.get("version")
                            else:
                                result["software_agent"] = str(agent)
                
                # Hash data assertion
                if "c2pa.hash" in label:
                    if isinstance(data, dict):
                        result["hash_algorithm"] = data.get("alg") or data.get("algorithm")
                        result["pad"] = data.get("pad")
                
                # Ingredient assertions (relationships)
                if "c2pa.ingredient" in label:
                    if isinstance(data, dict):
                        result["relationship"] = data.get("relationship")

        # Extract signature info
        if "signature_info" in manifest:
            sig_info = manifest["signature_info"]
            if isinstance(sig_info, dict):
                # Timestamp
                if "time" in sig_info:
                    result["date_created"] = sig_info["time"]
                
                # Algorithm
                if "alg" in sig_info:
                    result["alg"] = sig_info["alg"]
                
                # Certificate issuer
                if "issuer" in sig_info:
                    result["cert_issuer"] = sig_info["issuer"]
                
                # Time stamp authority
                if "ta_url" in sig_info:
                    result["ta"] = sig_info["ta_url"]
                
                # Time stamp token
                if "tsa" in sig_info:
                    result["tst"] = sig_info["tsa"]
        
        # Extract claim info
        if "claim" in manifest:
            claim = manifest["claim"]
            if isinstance(claim, dict):
                if "alg" in claim:
                    result["alg"] = claim["alg"]
                if "hash" in claim:
                    result["hash_algorithm"] = claim["hash"]

        # Validation status
        if "validation_status" in manifest:
            status_list = manifest["validation_status"]
            if isinstance(status_list, list):
                if len(status_list) == 0:
                    result["validation_status"] = "valid"
                else:
                    # Check if any validation failed
                    has_error = any("error" in str(s).lower() or "fail" in str(s).lower() for s in status_list)
                    result["validation_status"] = "invalid" if has_error else "valid"
            else:
                result["validation_status"] = "valid"
        else:
            result["validation_status"] = "valid"  # Assume valid if no status field

    except Exception as e:
        # If extraction fails, return partial data
        print(f"Warning: Manifest extraction failed: {e}")

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
            except (OSError, IOError):
                pass  # Best effort cleanup


# Configuration - use environment variables with sensible defaults
import os
SIGNED_OUTPUT_DIR = Path(os.getenv("C2PA_SIGNED_OUTPUT_DIR", Path.home() / "Pictures" / "Signed"))
DEFAULT_CREATOR = os.getenv("C2PA_DEFAULT_CREATOR", "the operator James [scrubbed]")


# C2PA Tool paths
C2PA_TOOL_DIR = Path(__file__).parent.parent.parent / "tools" / "c2pa"
C2PATOOL_EXE = C2PA_TOOL_DIR / "c2patool" / "c2patool.exe"
C2PA_MANIFEST_TEMPLATE = C2PA_TOOL_DIR / "signing_manifest.json"


def _ensure_signing_manifest():
    """Ensure the signing manifest template exists."""
    manifest = {
        "alg": "es256",
        "private_key": "c2patool/sample/es256_private.key",
        "sign_cert": "c2patool/sample/es256_certs.pem",
        "ta_url": "http://timestamp.digicert.com",
        "claim_generator_info": [{
            "name": "iHIM",
            "version": "1.0.0"
        }],
        "title": "{{TITLE}}",
        "assertions": [
            {
                "label": "stds.schema-org.CreativeWork",
                "data": {
                    "@type": "CreativeWork",
                    "author": [{"@type": "Person", "name": "{{CREATOR}}"}],
                    "dateCreated": "{{DATE}}"
                }
            },
            {
                "label": "c2pa.actions",
                "data": {
                    "actions": [{"action": "{{ACTION}}"}]
                }
            }
        ]
    }

    if not C2PA_MANIFEST_TEMPLATE.exists():
        with open(C2PA_MANIFEST_TEMPLATE, "w") as f:
            json.dump(manifest, f, indent=2)

    return manifest


@router.post("/sign")
def sign_image(
    image_file: UploadFile = File(...),
    creator: Optional[str] = Form(None),
    title: Optional[str] = Form(None),
    action: Optional[str] = Form("c2pa.created")
):
    """
    Sign an image with C2PA metadata using c2patool.exe (Rust CLI).

    Note: Uses c2patool.exe instead of c2pa-python due to certificate
    validation differences. The Rust CLI works with self-signed certs,
    enabling sovereign signing without CA fees.

    Parameters:
    - image_file: Image to sign (required)
    - creator: Content creator name (default: the operator James [scrubbed])
    - title: Optional title for the content
    - action: C2PA action type (default: c2pa.created)

    Returns the path to the signed image.
    """
    import subprocess
    from datetime import datetime

    temp_file_path = None
    temp_manifest_path = None

    try:
        # Check if c2patool.exe exists
        if not C2PATOOL_EXE.exists():
            return {
                "success": False,
                "error": f"c2patool.exe not found at {C2PATOOL_EXE}",
                "message": "C2PA signing tool not available"
            }

        # Ensure output directory exists
        SIGNED_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        # Get file extension
        original_filename = image_file.filename or "image.jpg"
        ext = os.path.splitext(original_filename)[1].lower()
        if ext not in ['.jpg', '.jpeg', '.png', '.webp', '.gif', '.tiff', '.tif']:
            ext = '.jpg'

        # Generate output filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = os.path.splitext(original_filename)[0]
        output_filename = f"{base_name}_signed_{timestamp}{ext}"
        output_path = SIGNED_OUTPUT_DIR / output_filename

        # Save uploaded file to temp location
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            temp_file_path = tmp.name
            content = image_file.file.read()
            tmp.write(content)

        # Create manifest JSON with actual values (absolute paths)
        manifest = {
            "alg": "es256",
            "private_key": str(C2PA_TOOL_DIR / "c2patool" / "sample" / "es256_private.key"),
            "sign_cert": str(C2PA_TOOL_DIR / "c2patool" / "sample" / "es256_certs.pem"),
            "ta_url": "http://timestamp.digicert.com",
            "claim_generator_info": [{
                "name": "iHIM",
                "version": "1.0.0"
            }],
            "title": title or original_filename,
            "assertions": [
                {
                    "label": "stds.schema-org.CreativeWork",
                    "data": {
                        "@type": "CreativeWork",
                        "author": [{"@type": "Person", "name": creator or DEFAULT_CREATOR}],
                        "dateCreated": datetime.now().isoformat()
                    }
                },
                {
                    "label": "c2pa.actions",
                    "data": {
                        "actions": [{"action": action or "c2pa.created"}]
                    }
                }
            ]
        }

        # Write temp manifest
        with tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="w") as tmp:
            temp_manifest_path = tmp.name
            json.dump(manifest, tmp, indent=2)

        # Run c2patool.exe
        cmd = [
            str(C2PATOOL_EXE),
            temp_file_path,
            "-m", temp_manifest_path,
            "-o", str(output_path),
            "-f"  # Force overwrite
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(C2PA_TOOL_DIR)  # Run from tool dir so relative paths work
        )

        if result.returncode != 0:
            return {
                "success": False,
                "error": result.stderr or "Unknown error",
                "stdout": result.stdout,
                "message": "C2PA signing failed"
            }

        # Parse output JSON for manifest info
        try:
            manifest_info = json.loads(result.stdout) if result.stdout else {}
        except json.JSONDecodeError:
            manifest_info = {"raw_output": result.stdout}

        return {
            "success": True,
            "message": "Image signed successfully (sovereign signing)",
            "output_path": str(output_path),
            "output_filename": output_filename,
            "creator": creator or DEFAULT_CREATOR,
            "manifest_info": manifest_info,
            "note": "Signed with self-signed certificate. Verifiers will show 'Unknown Source' - this is expected for sovereign signing."
        }

    except HTTPException:
        raise

    except Exception as e:
        import traceback
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
            "message": "Error signing image"
        }

    finally:
        # Clean up temp files
        for path in [temp_file_path, temp_manifest_path]:
            if path and os.path.exists(path):
                try:
                    os.unlink(path)
                except (OSError, IOError):
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


@router.get("/download/{filename}")
def download_signed_image(filename: str):
    """Download a specific signed image."""
    file_path = SIGNED_OUTPUT_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="application/octet-stream"
    )


@router.get("/status")
def c2pa_status():
    """C2PA module status check."""
    return {
        "module": "c2pa",
        "status": "active",
        "output_dir": str(SIGNED_OUTPUT_DIR),
        "default_creator": DEFAULT_CREATOR,
        "features": ["verify", "sign", "list signed images", "download"]
    }
