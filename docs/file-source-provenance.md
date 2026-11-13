# File source provenance

File receipts identify the `StorageFileItem.id`, not the storage key. A
`created` receipt records upload registration and the authenticated admin who
registered it. Registration does not establish that storage contains the bytes.

A `verified` receipt records the authenticated admin who confirmed that the
fetched object matched the registered checksum and size. Recovery can therefore
have a different writer from registration. An uncertain, missing, or mismatched
object is not verified. A `deleted` receipt records the admin who requested
logical deletion; later storage cleanup does not create a new receipt.

Receipts contain a hash of the upload metadata and phase, never file bytes or
credentials. The client-supplied `source_agent` is metadata, not evidence of
identity. Repeated registration, verification, or deletion does not create a
duplicate receipt for the same completed transition. If a legacy file first
enters provenance during verification or deletion, its creator remains unknown.
Upload preparation and verification calls without an authenticated actor are
recorded as unattributed.
