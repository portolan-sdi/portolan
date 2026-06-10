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
- Arabic: Modern Standard Arabic (MSA). Translate the idea in context, never word by
  word. When the literal calque reads wrong or unnatural to Arab developers (for example
  object storage, tile servers, bucket), keep the English term in Latin rather than force
  an awkward Arabic word. Render "-native" as "مصمّم لـ" (cloud-native = مصمّم للسحابة,
  AI-native = مصمّم للذكاء الاصطناعي), never "أصيل". A Latin term inside Arabic takes
  "داخل/فوق", not "في" (داخل Object Storage, not في Object Storage).
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
| object storage | almacenamiento de objetos | Object Storage (Latin) |
| cloud-native | nativo de la nube | مصمّم للسحابة |
| geospatial data | datos geoespaciales | البيانات الجيومكانية |
| spatial data | datos espaciales | البيانات المكانية |
| spatial data infrastructure | infraestructura de datos espaciales (SDI) | البنية التحتية للبيانات المكانية |
| sovereign | soberano | سيادي |
| AI-native | nativo de IA | مصمّم للذكاء الاصطناعي |
| AI-ready | listo para IA | جاهز للذكاء الاصطناعي |
| browser-native | nativo del navegador | يعمل داخل المتصفح |
| cheap | económico | اقتصادي |
| egress | transferencia de salida | نقل البيانات الصادرة |
| jurisdiction | jurisdicción | داخل حدود بلدك |
| bucket | bucket | مساحة التخزين |
| validator | validador | أداة التحقق |
| viewer | visor | عارض |
| browser | navegador | متصفّح |
| node | nodo | عقدة |
| GIS | SIG | نظم المعلومات الجغرافية |
| range request | solicitud por rango | طلب النطاق الجزئي |
| tile server | servidor de teselas | خوادم tiles (Latin) |
| map tiles | teselas de mapa | map tiles (Latin) |

## Notes

- Spanish "SDI" is standardized as "IDE", which collides with "code editor". Keep the
  Latin "SDI" in body copy to avoid confusion.
- Keep `portolan-cli`, `portolan-viewer`, `portolan-skills`, `v1.0.0a0` Latin everywhere.
