# Portolan translation glossary (en · es · ar)

Single source of truth for terminology across `messages/`. When adding or changing
any user-facing string, follow this table and keep all three locale files in sync.

## Policy

- Product and format names stay Latin in every locale and are bidi-isolated in Arabic:
  Portolan, STAC, GeoParquet, COG, Parquet, GeoTIFF, PMTiles, COPC, FlatGeobuf, Zarr,
  S3, DuckDB, AWS, GCS, Azure, R2, MinIO, Apache-2.0.
- Generic concept words are translated (see table).
- Digits are always Latin (0-9), including in Arabic prose.
- Spanish: neutral international Spanish, impersonal register.
- Arabic: Modern Standard Arabic (MSA). For borderline dev terms lead with Arabic.
- No em dashes, colons, or semicolons in es or ar copy.

## Core terms

| English | Spanish (es) | Arabic (ar) |
|---|---|---|
| documentation | Documentación / Docs | التوثيق |
| open source | código abierto | مفتوح المصدر |
| open governance | gobernanza abierta | حوكمة مفتوحة |
| toolkit | kit / conjunto de herramientas | حزمة أدوات |
| conventions | convenciones | الأعراف |
| quickstart | Inicio rápido | البدء السريع |
| publish | publicar | نشر |
| catalog | catálogo | كتالوج |
| metadata | metadatos | البيانات الوصفية |
| object storage | almacenamiento de objetos | تخزين الكائنات |
| cloud-native | nativo en la nube | سحابي |
| spatial data infrastructure | infraestructura de datos espaciales (SDI) | البنية التحتية للبيانات المكانية |
| sovereign | soberano | سيادي |
| AI-ready | listo para IA | جاهز للذكاء الاصطناعي |
| cheap | económico | اقتصادي |
| validator | validador | أداة التحقق |
| viewer | visor | عارض |
| browser | navegador | متصفّح |
| node | nodo | عقدة |
| GIS | SIG | نظم المعلومات الجغرافية |
| range request | solicitud por rango | طلب النطاق |
| map tiles | teselas de mapa | بلاطات الخرائط |

## Notes

- Spanish "SDI" is standardized as "IDE", which collides with "code editor". Keep the
  Latin "SDI" in body copy to avoid confusion.
- Keep `portolan-cli`, `portolan-viewer`, `portolan-skills`, `v0.7.0` Latin everywhere.
