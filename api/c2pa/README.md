# C2PA Verification API

## Overview

The C2PA (Coalition for Content Provenance and Authenticity) API provides endpoints for verifying content authenticity and provenance metadata embedded in images.

## Endpoints

### POST `/api/c2pa/verify`

Verify C2PA metadata from an image URL or uploaded file.

**Parameters:**
- `image_url` (Form, optional): URL to download image from
- `image_file` (UploadFile, optional): Direct file upload

**Note:** One of `image_url` or `image_file` must be provided.

**Response (success with C2PA data):**
```json
{
  "success": true,
  "has_c2pa": true,
  "manifest": {
    "date_created": "2024-01-15T10:30:00Z",
    "author": "John Doe",
    "claim_generator": "Adobe Photoshop 25.0",
    "cert_issuer": "DigiCert",
    "format": "image/jpeg",
    "validation_status": "valid",
    "raw": { ... }
  }
}
```

**Response (success, no C2PA data):**
```json
{
  "success": true,
  "has_c2pa": false,
  "message": "No C2PA manifest found in image"
}
```

**Response (library not installed):**
```json
{
  "success": false,
  "has_c2pa": false,
  "error": "c2pa-python library not installed",
  "message": "Install with: pip install c2pa-python"
}
```

**Response (error):**
```json
{
  "success": false,
  "has_c2pa": false,
  "error": "error details",
  "message": "Error processing image"
}
```

### GET `/api/c2pa/status`

Check C2PA module status.

**Response:**
```json
{
  "module": "c2pa",
  "status": "active",
  "features": ["verify (POC)", "manifest generation (frontend)"]
}
```

## Usage Examples

### Python (httpx)

```python
import httpx

# Verify from URL
response = httpx.post(
    "http://127.0.0.1:7777/api/c2pa/verify",
    data={"image_url": "https://example.com/image.jpg"}
)
print(response.json())

# Verify from file upload
with open("image.jpg", "rb") as f:
    response = httpx.post(
        "http://127.0.0.1:7777/api/c2pa/verify",
        files={"image_file": f}
    )
    print(response.json())
```

### cURL

```bash
# Verify from URL
curl -X POST "http://127.0.0.1:7777/api/c2pa/verify" \
  -d "image_url=https://example.com/image.jpg"

# Verify from file upload
curl -X POST "http://127.0.0.1:7777/api/c2pa/verify" \
  -F "image_file=@/path/to/image.jpg"
```

### JavaScript (fetch)

```javascript
// Verify from URL
const response = await fetch('http://127.0.0.1:7777/api/c2pa/verify', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/x-www-form-urlencoded',
  },
  body: new URLSearchParams({
    image_url: 'https://example.com/image.jpg'
  })
});
const data = await response.json();
console.log(data);

// Verify from file upload
const formData = new FormData();
formData.append('image_file', fileInput.files[0]);
const response = await fetch('http://127.0.0.1:7777/api/c2pa/verify', {
  method: 'POST',
  body: formData
});
const data = await response.json();
console.log(data);
```

## Dependencies

### Required
- `fastapi>=0.115.6`
- `httpx>=0.27.0` (for URL downloads)
- `python-multipart>=0.0.9` (for file uploads)

### Optional
- `c2pa-python` (for actual C2PA verification)

Install optional dependencies:
```bash
pip install c2pa-python
```

## Implementation Notes

1. **Blocking I/O**: The `verify_c2pa` function uses `def` (not `async def`) because `c2pa-python` is a blocking library.

2. **Temp Files**: Images are downloaded/saved to temporary files for processing and automatically cleaned up after verification.

3. **Graceful Degradation**: If `c2pa-python` is not installed, the endpoint returns a helpful error message instead of crashing.

4. **File Extensions**: The implementation preserves file extensions from uploads/URLs to ensure proper image format detection.

5. **Timeout**: URL downloads have a 30-second timeout to prevent hanging connections.

## Security Considerations

1. **Input Validation**: Both URL and file inputs are validated before processing.
2. **Temp File Cleanup**: All temporary files are cleaned up in a `finally` block to prevent disk space issues.
3. **Error Handling**: Errors are caught and returned as structured responses (no stack traces to clients).
4. **Size Limits**: FastAPI's default file size limits apply (no explicit override).

## Future Enhancements

- [ ] Add max file size configuration
- [ ] Add support for batch verification
- [ ] Cache verification results by content hash
- [ ] Add webhook support for async verification
- [ ] Support additional image formats (HEIC, AVIF)
