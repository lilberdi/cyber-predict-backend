package docs

import "embed"

// FS is the OpenAPI spec and Swagger UI page, baked into the API binary.
//
//go:embed openapi.yaml swagger/index.html dashboard/index.html
var FS embed.FS
