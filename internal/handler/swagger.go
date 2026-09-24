package handler

import (
	"io/fs"
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/lilberdi/cyber-predict/docs"
)

func serveOpenAPI(c *gin.Context) {
	raw, err := docs.FS.ReadFile("openapi.yaml")
	if err != nil {
		c.String(http.StatusInternalServerError, "openapi spec missing")
		return
	}
	c.Data(http.StatusOK, "application/yaml; charset=utf-8", raw)
}

func serveSwaggerUI(c *gin.Context) {
	name := strings.TrimPrefix(c.Param("filepath"), "/")
	if name == "" || name == "/" {
		name = "index.html"
	}
	raw, err := fs.ReadFile(docs.FS, "swagger/"+name)
	if err != nil {
		c.Status(http.StatusNotFound)
		return
	}
	ctype := "text/html; charset=utf-8"
	if strings.HasSuffix(name, ".css") {
		ctype = "text/css; charset=utf-8"
	}
	c.Data(http.StatusOK, ctype, raw)
}
