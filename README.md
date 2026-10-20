# term-wyrm
Legendary legless dragon and guardian of terms. This is refactor of search dragon. 

## Install

```bash
pip install term-wyrm          # library only, no dependencies
pip install 'term-wyrm[rich]'  # adds Rich tables to the CLI
```

## Library

```python
from term_wyrm import SearchService

service = SearchService(["ols", "ols2", "umls"])  # umls needs UMLS_API_KEY
result = service.search("HP:0001250", ["HP", "MONDO"])
for concept in result:
    print(concept.code, concept.display, concept.system)
result.to_dict()   # JSON-ready
result.failures    # APIs that couldn't answer; the rest still did

service.descendants("HP:0002197")
service.children("generalized-onset seizure", "HP")
```

## CLI

```bash
term-wyrm search seizure HP:0001250 -o HP,MONDO
term-wyrm search seizure -a ols2,umls -n 50 -f csv --output seizure.csv
term-wyrm descendants HP:0002197 --parent -f json
term-wyrm children "generalized-onset seizure" -o HP
```

`-f` takes `table` (Rich if installed, otherwise plain), `rich`, `plain`,
`csv`, or `json`. With `--output`, the format follows the file extension.
Exit status: 0 found, 1 nothing found, 2 bad arguments, 3 an API failed.
