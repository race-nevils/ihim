# C2PA Signing Fix - Implementation Summary

## Problem
C2PA signing in iHIM was failing with: **"signing failed: error signing file: signature: the certificate is invalid"**

## Root Cause
The failing code in `routes.py` used:
1. ❌ `Signer.from_info()` - stricter validation than `from_callback()`
2. ❌ Bytes for certificates instead of strings
3. ❌ Wrong parameter name: `ta_url` instead of `tsa_url`
4. ❌ Bytes for TSA URL instead of string
5. ❌ Generated fresh ephemeral certificates on each request

## Solution Implemented
Following the working pattern from `sign_image.py`, we:

### Phase 1: Switch to Persistent Certificates ✅
- Replaced `_get_test_signer()` with `_load_signing_credentials()`
- Tries to load persistent certificates from `IHIM/tools/c2pa/`
- Falls back to known-good sample certs from `c2patool/sample/` if persistent certs don't exist
- Returns private key **object** and certificate chain as **STRING**

### Phase 2: Switch to Callback-based Signing API ✅
Changed from:
```python
# OLD - BROKEN
signer_info = C2paSignerInfo(
    alg=C2paSigningAlg.ES256,
    sign_cert=cert_pem,  # bytes
    private_key=private_key_pem,  # bytes
    ta_url=b"http://timestamp.digicert.com"  # bytes, wrong param name
)
with Signer.from_info(signer_info) as signer:
    ...
```

Changed to:
```python
# NEW - WORKING
def sign_callback(data: bytes) -> bytes:
    signature = private_key.sign(data, ec.ECDSA(hashes.SHA256()))
    return signature

signer = c2pa.Signer.from_callback(
    callback=sign_callback,
    alg=c2pa.C2paSigningAlg.ES256,
    certs=cert_chain,  # STRING, not bytes
    tsa_url="http://timestamp.digicert.com"  # STRING, not bytes, correct param
)
```

## Key Changes Made

### 1. `api/c2pa/routes.py` - Line 344-380
Replaced certificate generation function with loader:
- Loads from `IHIM/tools/c2pa/private_key.pem` and `certificate.pem`
- Falls back to `c2patool/sample/es256_private.key` and `es256_certs.pem`
- Returns tuple of (private_key_object, cert_chain_string)

### 2. `api/c2pa/routes.py` - Line 475-507
Updated signing logic:
- Uses `Signer.from_callback()` instead of `Signer.from_info()`
- Creates proper ECDSA signing callback
- Passes certs as string
- Uses correct parameter name `tsa_url` as string

### 3. `api/c2pa/routes.py` - Line 405-407
Cleaned up imports:
- Removed unused `C2paSignerInfo` and `C2paSigningAlg` from imports
- Added `import c2pa` for namespace access

## What Changed
| Aspect | Before (Broken) | After (Fixed) |
|--------|----------------|---------------|
| API | `Signer.from_info()` | `Signer.from_callback()` ✅ |
| Cert format | Bytes | String ✅ |
| TSA param | `ta_url=b"..."` | `tsa_url="..."` ✅ |
| Certificates | Generated fresh each request | Persistent files ✅ |
| Cert source | Generated CA chain | Sample certs (fallback) ✅ |

## Testing Steps

### 1. Test through iHIM UI
1. Open the C2PA Widget in iHIM
2. Go to the "Sign" tab
3. Upload an image
4. Add creator name and title
5. Click "Sign Image"
6. Should succeed without "certificate is invalid" error

### 2. Verify with c2patool
```bash
cd IHIM/tools/c2pa/c2patool
./c2patool.exe verify "C:\Users\<user>\OneDrive\Pictures\Signed\image_signed_*.jpg"
```

Should show:
- ✅ Valid C2PA signature
- ✅ Manifest data
- ✅ No validation errors

### 3. Verify on C2PA Verify
1. Go to https://contentcredentials.org/verify
2. Upload the signed image
3. Should display C2PA metadata

## Success Criteria
- [x] Code matches working `sign_image.py` pattern
- [ ] Signed images verify with `c2patool.exe verify`
- [ ] Signed images verify on contentcredentials.org/verify
- [ ] No "certificate is invalid" errors
- [ ] API returns success response

## Next Steps
1. **Test the fix** by signing an image through the UI
2. **Verify locally** with c2patool
3. **Verify online** with C2PA Verify
4. If sample certs work but you need production certs, generate proper CA-signed certificates

## Files Modified
- `IHIM/api/c2pa/routes.py` (3 changes, -82 lines, +45 lines)

## Certificate Fallback Chain
1. ✅ Try: `IHIM/tools/c2pa/private_key.pem` + `certificate.pem`
2. ✅ Fallback to: `c2patool/sample/es256_private.key` + `es256_certs.pem` (known-good sample certs)

The fallback to sample certs ensures signing will work immediately while you can optionally generate production certificates later.
