# Техническое задание
## Набор утилит для создания многоязычных ShieldFont-шрифтов, OpenType-подстановок, CSS и JS-кодека

**Рабочее название проекта:** `ShieldFont Toolchain`  
**Версия документа:** 1.1 (TrueType-only)  
**Дата:** 5 августа 2026 г.  
**Базовый репозиторий для анализа:** `alexeydott/shieldfont`, ветка `main`, снимок `d6efb2d3972569628e870ff2767cd29412c245ee`  
**Статус:** техническое задание на проектирование и реализацию

---

## 0. Назначение документа

Документ фиксирует:

1. фактическую архитектуру и стек текущего репозитория `shieldfont`;
2. сильные стороны и ограничения существующей реализации;
3. целевую архитектуру нового набора утилит;
4. форматы конфигурации, словарей и артефактов;
5. алгоритмы генерации OpenType GSUB;
6. требования к сборке TrueType TTF и WOFF2 с таблицей `glyf`;
7. требования к CSS и JavaScript-кодеку;
8. требования к вспомогательным средствам перевода и генерации словарей через LLM;
9. план реализации, Quality Gates и критерии приёмки.

Анализ выполнен по исходным файлам генератора, кодека, пакетов, тестов, документации и CI. Бинарные WOFF2-файлы в рамках данного анализа отдельно не декомпилировались; их структура и ожидаемое поведение подтверждаются исходным кодом генератора и аудитора шрифтов.

---

# Часть I. Анализ существующего репозитория

## 1. Назначение существующего проекта

Текущий ShieldFont реализует двустороннюю подмену слов:

- исходный текст на этапе сборки или серверного рендеринга преобразуется в правдоподобный текст-приманку;
- в HTML отправляется уже подменённый текст;
- специальный шрифт содержит GSUB-правила, которые при шейпинге заменяют последовательность глифов слова-приманки на составной глиф, визуально изображающий исходное слово;
- читатель видит исходный текст, а обработчик HTML без загрузки и шейпинга шрифта получает текст-приманку. [R1]

Проект прямо указывает, что шрифт является доступным для скачивания «кодовым кольцом»: мотивированный обработчик может извлечь подстановки из GSUB и контуров. Механизм повышает стоимость массового сбора, но не является криптографической защитой. [R1][R12]

## 2. Структура и стек

Репозиторий является смешанным monorepo. В корне находятся `packages`, `scripts`, `benchmark`, `docs`, `examples` и GitHub Actions. [R2]

### 2.1. Основные языки

По данным GitHub Language API в снимке репозитория представлены TypeScript, JavaScript, Python, Shell и CSS; наибольший объём приходится на TypeScript. [R3]

### 2.2. JavaScript/TypeScript-часть

Корневой `package.json` использует npm workspaces:

- `packages/core`;
- `packages/react`;
- `packages/font`. [R4]

`@shieldfont/core`:

- TypeScript;
- ESM;
- Node.js `>=20.10`;
- компиляция через `tsc`;
- тесты через Vitest;
- содержит каноническую логику кодирования/декодирования, типы, загрузку mapping-файлов и дополнительные механизмы HTML/маркировки. [R5][R6]

`@shieldfont/react`:

- React 18+;
- TypeScript;
- зависит от `@shieldfont/core`;
- содержит компоненты `Shield`, `NonShield`, клиентский solver и вспомогательные механизмы доступности. [R7][R8]

`@shieldfont/font`:

- статический npm-пакет;
- содержит WOFF2-файлы, CSS и автономный ESM-кодек;
- предназначен для установки без собственного build step. [R9][R10]

### 2.3. Python-часть

Минимальные Python-зависимости текущего проекта:

- `fonttools[woff]`;
- `brotli`;
- `requests`. [R11]

Главный сборщик — монолитный скрипт `scripts/generate_font.py`. Дополнительно имеются:

- `audit_font.py`;
- `subset_font.py`;
- `reseed_mapping.py`;
- `drop_glyph_names.py`;
- `fix_composite_lsb.py`;
- средства stamping и smoke tests. [R13]

### 2.4. Тестовый стек и CI

CI запускает:

- Node 20 и 22 на Ubuntu и macOS;
- TypeScript build и Vitest;
- Playwright-аудиты;
- axe-core;
- отдельную проверку NVDA на Windows;
- Python 3.12;
- проверку метрик составных глифов;
- smoke test всех Python-скриптов. [R14]

## 3. Текущий пайплайн создания шрифта

### 3.1. Входные данные

Главный генератор принимает:

- локальный базовый файл или URL;
- имя семейства и файловый prefix;
- один JSON mapping;
- вес и subfamily;
- параметры обработки таблицы `post` и salt имён глифов. [R15]

Mapping в текущем проекте — плоский JSON-объект вида:

```json
{
  "source": "decoy",
  "decoy": "source"
}
```

Служебные ключи с `_` игнорируются. Перед построением шрифта генератор удаляет коллизии many-to-one, чтобы один encoded target не мог визуально раскрываться в два разных source. [R16]

### 3.2. Создание глифов

Для каждого многосимвольного исходного слова генератор:

1. находит в `cmap` глиф каждого символа исходного слова;
2. создаёт новый составной `glyf`-глиф;
3. размещает компоненты последовательно по advance width;
4. рассчитывает bounding box;
5. записывает `hmtx`, причём `leftSideBearing` приравнивается к `xMin`;
6. создаёт отдельные варианты для lowercase, Capitalized и ALL CAPS. [R16][R17]

Имена создаваемых глифов не содержат открытый текст. Используется детерминированное salted-hash имя `word.<hash>`. Для web-версии таблица `post` переводится в format 3.0, чтобы вообще удалить имена глифов. [R18]

### 3.3. Направление GSUB

Направления кодека и шрифта противоположны:

- кодек: `source → target`;
- шрифт: последовательность глифов `target → составной глиф source`.

Это принципиальный контракт: mapping, JS-кодек и шрифт должны быть собраны из одного нормализованного набора правил.

### 3.4. Проверка границ слова

Наивная лигатура сработала бы внутри более длинного слова. Текущая реализация использует схему **fire-then-revert**:

1. Lookup A, `LigatureSubst`: подстановка target-последовательности в составной source-глиф срабатывает без проверки границы;
2. Lookup B, `SingleSubst`: односивольные подстановки, в текущем словаре — цифры;
3. Lookup C, `MultipleSubst`: обратное разложение составного глифа обратно в target-глифы;
4. Lookup D, `ChainContextSubst`: вызывает Lookup C, если перед результатом находится буква;
5. Lookup E, `ChainContextSubst`: вызывает Lookup C, если после результата находится буква. [R17][R19]

Таким образом, подстановка сохраняется у отдельного слова и отменяется внутри большего буквенного токена. Эта схема также работает на границах shaping run, где невозможно потребовать обязательный «небуквенный» символ слева или справа. [R17]

### 3.5. Работа с большими GSUB

Существующий генератор учитывает 16-битные ограничения внутренних offset’ов:

- разбивает `LigatureSubst` на несколько ограниченных по размеру subtables;
- разбивает `MultipleSubst`;
- сортирует coverage по glyph ID;
- перемещает новые lookup’и в начало `LookupList`;
- перенумеровывает ссылки на lookup’и во всех feature/context records. [R17][R19]

Это не второстепенная оптимизация, а обязательная часть масштабируемой реализации: словарь в несколько тысяч или десятков тысяч правил нельзя собирать как одну неограниченную таблицу.

### 3.6. Подключение feature

Текущая основная реализация подключает созданные lookup’и к feature `ccmp`. Если `ccmp` отсутствует, feature создаётся и добавляется в существующие Script/LangSys. [R19]

Резервный код построения GSUB с нуля создаёт `DFLT` и `latn`, но текущая архитектура не поддерживает независимый mapping для `DFLT`, `latn`, `cyrl` или отдельных языковых систем: один и тот же набор правил фактически является глобальным. [R15][R19]

### 3.7. Поддержка форматов

Фактически текущий production-путь рассчитан на шрифты с TrueType outlines (`glyf`). Документация прямо указывает, что CFF/OTF отклоняется и предлагается найти TTF-вариант. Variable font приводится к статическому экземпляру по умолчанию. [R20]

Генератор сохраняет:

- TTF;
- WOFF2;
- CSS;
- согласованный mapping JSON. [R16]

### 3.8. CSS

Custom-font generator создаёт базовый `@font-face`. Публикуемый пакет содержит более развитый CSS:

- отдельные shielded faces;
- отдельный neutral face без подстановок;
- `font-display: block`;
- классы для выбора variant. [R10][R16]

### 3.9. JavaScript-кодек

Канонический кодек:

- нормализует текст в NFC;
- токенизирует Unicode letter runs через `\p{L}+`;
- сохраняет регистр;
- не изменяет HTML character references;
- безопасно читает только собственные свойства mapping-объекта;
- отдельно обрабатывает контекст цифр. [R6]

В текущем словаре mapping является involution, поэтому `decode()` реализован как повторный вызов `encode()`. Это декодирование по словарю, а не динамический разбор OpenType-таблиц. [R6]

Автономный CDN-файл содержит копию логики и встроенный mapping; он генерируется shell-скриптом. Логика вручную зеркалируется из TypeScript и контролируется parity test. [R21][R22]

### 3.10. Проверка результата

`audit_font.py`:

- шейпит target через `hb-shape`;
- проверяет lowercase, Capitalized и ALL CAPS;
- проверяет отсутствие срабатывания коротких правил внутри более длинных слов;
- проверяет согласованность `hmtx.lsb` и `glyf.xMin`;
- формирует JSON и HTML отчёты. [R23]

`subset_font.py` умеет уменьшать готовый шрифт под фактический словарь сайта. Перед glyph subsetting он симметрично удаляет правила из всех lookup’ов схемы fire-then-revert и обязательно выпускает согласованный урезанный mapping. [R24]

## 4. Сильные стороны текущего решения

1. Реально работающая схема word-boundary подстановок без ложных срабатываний на границах shaping run.
2. Обработка больших GSUB и offset overflow.
3. Синхронизация font mapping и encoder mapping.
4. Unicode-aware токенизация и защита HTML entities.
5. Проверка браузерно-значимых метрик составных глифов.
6. Воспроизводимые имена глифов и возможность удалить их из web-font.
7. Разделение runtime-кодека, React-интеграции и font builder.
8. CI, включающий шейпинг, browser tests и accessibility checks.

## 5. Ограничения относительно требуемого пайплайна

| Требование | Текущее состояние | Требуемое изменение |
|---|---|---|
| TTF и WOFF2 на входе | Production-путь использует `glyf`; WOFF2 поддерживается как контейнер TrueType | Зафиксировать TrueType-only scope; автоматически распаковывать WOFF2 и отклонять шрифты без `glyf` |
| Новый font family/name | Реализовано частично | Полная модель имён, versioning, unique ID, PostScript name, description/license metadata |
| Несколько script/language scopes | Один глобальный mapping | Независимые lookup groups на scope; корректный ScriptList/LangSys |
| CSV key-value | JSON | CSV parser, normalizer, merger, validator, экспорт нормализованного JSON |
| Генерация `.fea` | Таблицы строятся напрямую через `otTables` | Обязательный человекочитаемый `.fea`; компиляция через feaLib либо эквивалентный backend |
| Отдельный `DFLT`, `latn`, `cyrl` | Нет независимых словарей | Конфигурация scope и отрицательные cross-scope tests |
| JS обратное декодирование | Только один mapping/involution | Scope-aware encoder/decoder; поддержка направленных и involutive mappings |
| Перевод | Нет | Provider-neutral translation utility |
| Словарь из текста/LLM | Есть reseed по готовым buckets, но нет общего LLM workflow | Extraction → candidate generation → deterministic validation → review → approved CSV |
| Единый CLI/конфигурация | Набор отдельных скриптов | Один CLI, общая библиотека, единый manifest и логирование |
| Версионирование | В snapshot есть рассинхронизация root/package versions | Один источник версии и build ID [R4][R5][R7][R9] |

---

# Часть II. Целевая система

## 6. Цель проекта

### 6.1. Ограничение версии 1: только TrueType

Версия 1 проектируется исключительно для шрифтов с quadratic TrueType outlines в таблице `glyf`. Допустимые контейнеры — `.ttf` и `.woff2`; WOFF2 должен после распаковки содержать `glyf`. Форматы `.otf`, CFF, CFF2, Type 1, bitmap-only fonts и конвертация между outline flavors не входят в область проекта и должны отклоняться до изменения исходного файла.

Разработать кроссплатформенный набор CLI-утилит и библиотек, который по декларативной конфигурации:

1. принимает TTF либо WOFF2, содержащий TrueType outlines в таблице `glyf`;
2. анализирует и нормализует исходный шрифт;
3. создаёт новый шрифт с заданными именами и metadata;
4. загружает один или несколько CSV-словарей;
5. связывает словари с encoder locale/script и OpenType Script/LangSys;
6. создаёт составные TrueType-глифы на основе компонентов `glyf`;
7. генерирует OpenType feature source;
8. компилирует GSUB и собирает итоговые TTF и WOFF2;
9. проверяет структурную и визуальную корректность;
10. выпускает CSS;
11. выпускает TypeScript/JavaScript-кодек для прямого и обратного преобразования;
12. формирует manifest, отчёты и checksums;
13. предоставляет дополнительные команды перевода и построения словарей из текста.

## 7. Терминология и модель областей действия

### 7.1. Разные идентификаторы языка

Система обязана различать:

- **BCP 47 locale** — используется приложением и JS-кодеком, например `en`, `ru`, `de-DE`;
- **Unicode Script** — используется токенизатором, например `Latn`, `Cyrl`;
- **OpenType Script tag** — четырёхбайтовый tag в GSUB, например `latn`, `cyrl`, `DFLT`;
- **OpenType LangSys tag** — зарегистрированный OpenType tag внутри конкретного Script;
- **DefaultLangSys** — отдельное поле Script table, а не LangSysRecord с именем `dflt`.

OpenType specification определяет `DFLT` как default script tag, `latn` как Latin и `cyrl` как Cyrillic. Спецификация также запрещает создавать LangSysRecord с tag `dflt`/`DFLT`; default language system должен записываться как `DefaultLangSys`. [S1][S2]

### 7.2. Scope

**Scope** — единица конфигурации, связывающая:

- входной язык/locale и script, по которым JS выбирает словарь;
- CSV-словари;
- OpenType script и DefaultLangSys/дополнительные LangSys;
- feature tag;
- правила регистра и границ токена.

### 7.3. Source и target

В CSV:

- `source` — исходное слово, которое должен видеть человек;
- `target` — encoded/decoy слово, записываемое в HTML или документ.

В шрифте строится правило `target glyph sequence → visual source glyph`.

### 7.4. Same-script и cross-script mapping

По умолчанию source и target должны принадлежать одному Unicode script. Cross-script mapping допускается только явно.

Причина: OpenType script при шейпинге определяется по encoded target-тексту. Если русское source-слово заменить Latin target-словом, GSUB будет выбираться для `latn`, а не для `cyrl`. Поэтому в cross-script scope должны раздельно задаваться:

- `encoder.sourceScript`;
- `encoder.locales`;
- `shaping.targetScript`;
- `shaping.openTypeScript`.

## 8. Архитектурные принципы

1. **Single source of truth.** После нормализации один manifest ruleset используется одновременно font builder, `.fea` generator и JS-codec generator.
2. **Fail closed for correctness.** Если mapping и font не согласованы, сборка завершается ошибкой; нельзя выпускать HTML, в котором target останется видимым человеку.
3. **Fail open only by explicit policy.** Отсутствующее правило может оставить source открытым, но не должно превращать его в нераскрываемый target.
4. **Детерминированность.** Одинаковые source font, config, dictionaries и tool version должны давать byte-identical output при включённом reproducible mode.
5. **Core build offline.** Сборка шрифта не должна требовать сети. Translation и LLM-модули изолированы и необязательны.
6. **Feature source is an artifact.** Система всегда сохраняет `.fea`, даже если для крупных таблиц используется дополнительная программная постобработка.
7. **Preserve existing layout.** Существующие GSUB/GPOS не удаляются без явного параметра.
8. **Script isolation.** Lookup одного scope не должен случайно применяться в другом scope.
9. **Explicit mapping exposure.** Встраивание словаря в browser JS выключено по умолчанию.
10. **Плагинная модель внешних сервисов.** Translator и LLM provider реализуются через интерфейсы; подсистема шрифтов использует единственную TrueType-реализацию на базе `glyf`.

---

# Часть III. Рекомендуемый стек

## 9. Основной стек

### 9.1. Font/build layer

- Python 3.12+;
- `fontTools[woff]` как основной API работы с SFNT/GSUB/WOFF2;
- Brotli для WOFF2;
- `fontTools.feaLib` для генерации и компиляции feature source;
- HarfBuzz: `uharfbuzz` для in-process tests и/или официальный `hb-shape` для независимой CLI-проверки;
- `pydantic` для конфигурации и schema validation;
- `typer` или `click` для CLI;
- `PyYAML` либо `ruamel.yaml` для YAML;
- `pytest` и `hypothesis` для unit/property tests.

`TTFont` предоставляет доступ к таблицам шрифта и умеет читать/писать WOFF2 через `flavor="woff2"`; feaLib предоставляет `addOpenTypeFeatures()` для добавления `.fea` в `TTFont`. [S3][S4][S5]

### 9.2. Codec layer

- Node.js 20+;
- TypeScript 5+;
- ESM как основной формат;
- esbuild/tsup для ESM, CJS и IIFE;
- Vitest;
- Unicode property escapes;
- опционально `Intl.Segmenter`, но только как selectable tokenizer backend, а не единственный вариант.

### 9.3. Browser verification

- Playwright;
- Chromium, Firefox, WebKit;
- тестовая HTML-страница, подключающая итоговый CSS и WOFF2.

### 9.4. Translation/LLM layer

- provider adapters;
- HTTP-клиенты только в optional extra;
- SQLite cache;
- JSON Schema для структурированного ответа модели;
- обязательная фиксация provider/model/prompt hash/parameters в provenance.

## 10. Предлагаемая структура репозитория

```text
shieldfont-toolchain/
  pyproject.toml
  package.json
  README.md
  src/shieldfont/
    cli.py
    config/
      model.py
      schema.json
      loader.py
    font/
      inspect.py
      normalize.py
      names.py
      metadata.py
      glyf_builder.py
      glyph_factory.py
      gsub_builder.py
      feature_writer.py
      compiler.py
      writer.py
    dictionary/
      csv_reader.py
      normalize.py
      validate.py
      merge.py
      model.py
      matching.py
    verify/
      structural.py
      shaping.py
      browser.py
      report.py
    emit/
      css.py
      manifest.py
      checksums.py
    translate/
      base.py
      cli.py
      cache.py
      providers/
    llm_dictionary/
      extract.py
      candidates.py
      validate.py
      review.py
  packages/codec/
    src/
      tokenize.ts
      registry.ts
      encode.ts
      decode.ts
      types.ts
    test/
  templates/
    css/
    codec/
  tests/
    fonts/
    dictionaries/
    integration/
  docs/
```

---

# Часть IV. CLI и набор утилит

## 11. Единая команда

Главный executable: `shieldfont`.

Подкоманды:

```text
shieldfont init
shieldfont font inspect
shieldfont font unpack
shieldfont dict validate
shieldfont dict normalize
shieldfont dict merge
shieldfont features generate
shieldfont font build
shieldfont css build
shieldfont codec build
shieldfont verify
shieldfont build
shieldfont translate
shieldfont dict from-text
shieldfont clean
```

Каждая подкоманда должна быть доступна как Python API. CLI является thin wrapper, а не местом размещения бизнес-логики.

## 12. `shieldfont init`

### FR-INIT-001

Создаёт шаблон проекта:

```text
shieldfont.yml
fonts/
dictionaries/
texts/
dist/
```

### FR-INIT-002

Поддерживает параметры:

```text
--font PATH
--family NAME
--scripts DFLT,latn,cyrl
--force
```

### FR-INIT-003

Если указан исходный font, команда должна вызвать inspect и заполнить предлагаемые:

- family;
- subfamily;
- weight;
- style;
- наличие обязательной таблицы `glyf`;
- static/variable состояние и variation axes.

## 13. `shieldfont font inspect`

### FR-INSPECT-001

Принимает `.ttf` и `.woff2`. WOFF2 допускается только в том случае, если после распаковки шрифт содержит TrueType outlines в таблице `glyf`. Коллекции `.ttc` и любые CFF/CFF2-шрифты в версии 1 не поддерживаются.

### FR-INSPECT-002

Формирует human-readable и JSON отчёт:

- container format;
- sfnt version;
- наличие и параметры таблицы `glyf`;
- variable/static;
- axes and instances;
- name table;
- cmap coverage;
- scripts, определённые по Unicode coverage;
- GSUB/GPOS features;
- ScriptList/LangSys;
- glyph count;
- license-related name IDs;
- наличие DSIG;
- таблицы, которые будут удалены или изменены;
- предупреждения о Reserved Font Name.

### FR-INSPECT-003

Exit code должен быть ненулевым при:

- повреждённом SFNT;
- неверных checksums в strict mode;
- неизвестном WOFF2 transform;
- отсутствии таблицы `glyf`;
- наличии только `CFF`/`CFF2` outlines;
- невозможности выбрать face.

## 14. `shieldfont font unpack`

### FR-UNPACK-001

Команда предоставляет диагностическую декомпозицию, а не обязательный промежуточный формат сборки.

### FR-UNPACK-002

Выход:

```text
unpacked/
  font.ttx
  tables.json
  names.json
  cmap.csv
  layout/
    gsub.ttx
    gpos.ttx
    feature-inventory.json
  glyphs/
    glyph-order.txt
    metrics.csv
```

### FR-UNPACK-003

Опциональные флаги:

```text
--ttx
--layout-only
--glyphs-svg
--no-outlines
```

## 15. `shieldfont dict validate`

Проверяет один CSV либо все словари проекта.

### FR-DICT-VAL-001. Базовый CSV

Кодировка: UTF-8 с BOM;

Минимальный формат:

```csv
source,target
исходное,приманка
слово,замена
```

Допускаются aliases заголовков `key,value`, но normalizer всегда выводит `source,target`.

### FR-DICT-VAL-002. Расширенный CSV

Кодировка: UTF-8 с BOM;

```csv
source,target,enabled,case_mode,priority,tags,comment
исходное,приманка,true,auto,100,"noun;common",""
```

Поля:

- `source`: обязательное Unicode string;
- `target`: обязательное Unicode string;
- `enabled`: default `true`;
- `case_mode`: `exact|auto|lower|title|upper|all`;
- `priority`: integer;
- `tags`: `;`-separated metadata;
- `comment`: произвольный текст.

### FR-DICT-VAL-003. Нормализация

- UTF-8 с BOM;
- Unicode NFC;
- line endings LF в output;
- trim внешних whitespace, если `preserve_outer_space=false`;
- пустые source/target запрещены;
- control characters запрещены, кроме явно разрешённых;
- embedded newline запрещён для word mode;
- duplicate source обрабатывается по `duplicatePolicy`;
- exact duplicate удаляется с warning;
- self-map запрещён либо игнорируется по policy.

### FR-DICT-VAL-004. Инъективность

По умолчанию target должен быть уникальным внутри scope.

Режимы:

- `error` — сборка останавливается;
- `drop-lower-priority`;
- `keep-first`;
- `keep-last`.

`error` является значением по умолчанию. Автоматическое молчаливое удаление недопустимо.

### FR-DICT-VAL-005. Involution

Параметр `mappingMode`:

- `involution`: для каждой пары `a→b` требуется `b→a`;
- `bidirectional`: JS генерирует явный inverse map;
- `encode-only`: decoder не создаётся;
- `decode-only`: только диагностический режим.

### FR-DICT-VAL-006. Glyph coverage

После выбора source font validator проверяет, что:

- все code points target представлены в cmap;
- все code points source могут быть нарисованы;
- для cross-script mapping присутствуют оба набора glyphs;
- variation selector/combining sequence обрабатываются поддерживаемым sequence mode либо отклоняются.

### FR-DICT-VAL-007. Cross-scope collisions

Система обнаруживает:

- одинаковый target в двух scopes, которые подключены к одному OpenType Script/LangSys;
- один и тот же source с несовместимыми mappings для пересекающихся locales;
- ambiguous locale fallback;
- конфликт `DFLT` с конкретным script при включённом наследовании.

## 16. `shieldfont dict normalize`

Формирует:

- canonical CSV;
- canonical JSON;
- inverse JSON;
- статистику;
- hash ruleset.

Пример:

```text
dist/maps/ru-cyrl.csv
dist/maps/ru-cyrl.json
dist/maps/ru-cyrl.inverse.json
dist/reports/ru-cyrl.dictionary.json
```

Canonical ordering: сначала длина target по убыванию, затем target code-point order, затем source. Это обеспечивает детерминизм и приоритет длинных совпадений.

## 17. `shieldfont dict merge`

Поддерживает слои:

1. base dictionary;
2. language dictionary;
3. project overrides;
4. deny list;
5. generated candidates.

Конфликты всегда отражаются в отчёте с origin file и line number.

## 18. `shieldfont features generate`

### FR-FEA-001

Генерирует человекочитаемый `.fea` и machine-readable layout plan.

### FR-FEA-002

Для каждого scope создаются отдельные lookup namespaces:

```text
SF_<scope>_LIG_<n>
SF_<scope>_SINGLE_<n>
SF_<scope>_REVERT_<n>
SF_<scope>_CTX_BEFORE
SF_<scope>_CTX_AFTER
```

### FR-FEA-003

В feature source должны явно присутствовать `languagesystem`, `script` и `language`/default declarations. Feature File specification позволяет регистрировать lookup для нескольких script/language только явным повторным подключением; генератор не должен полагаться на неявное глобальное наследование. [S6]

### FR-FEA-004

Default feature tag: `ccmp`.

Конфигурация может разрешать:

- `ccmp`;
- `calt`;
- `liga`;
- custom registered tag;
- `ss01`–`ss20` только в opt-in режиме.

Для shield-поведения `ccmp` остаётся рекомендуемым default, потому что feature должен применяться автоматически; выключаемые discretionary features не обеспечивают стабильное раскрытие.

### FR-FEA-005

Lookup chunking:

- максимальный estimated subtable size задаётся конфигурацией;
- default должен иметь запас относительно 65535-byte offset limits;
- крупные lookup’и используют `useExtension` либо программную Extension wrapping;
- chunk boundaries детерминированы;
- longest target sequence размещается раньше короткой с тем же prefix.

### FR-FEA-006

Генератор обязан сохранить исходные GSUB/GPOS. Новые lookups вставляются в согласованном порядке. Все существующие lookup indices и context references должны быть корректно пересчитаны при прямой модификации таблиц.

## 19. `shieldfont font build`

### FR-FONT-001. Поддерживаемые входы

Обязательная поддержка:

- static TTF с таблицей `glyf`;
- WOFF2, который после распаковки содержит таблицу `glyf`;
- variable TTF (`glyf` + `fvar/gvar`) после обязательного выбора статического instance;
- variable WOFF2 с TrueType outlines после обязательного выбора статического instance.

Не поддерживаются и должны отклоняться до начала сборки: OpenType/CFF, CFF2, `.otf`, `.otc`, Type 1 и bitmap-only fonts.

### FR-FONT-002. Variable font

Конфигурация обязана задавать:

- named instance; либо
- координаты axes; либо
- `useDefaultInstance: true`.

Variable output в версии 1 не требуется. Результат всегда static: TTF и производный от него WOFF2.

### FR-FONT-003. TrueType glyph builder

```python
class TrueTypeGlyphBuilder(Protocol):
    def supports(font: TTFont) -> bool: ...
    def create_word_glyph(self, source: str, glyph_name: str) -> GlyphBuildResult: ...
    def finalize(self) -> None: ...
```

Единственная обязательная реализация — `GlyfCompositeBuilder`, создающая составные глифы из компонентов таблицы `glyf`. Отдельные outline backends и преобразование quadratic outlines в cubic outlines не предусматриваются.

### FR-FONT-004. Metrics

Для каждого output glyph:

- advance width = сумма advances компонентов с учётом shaping policy;
- LSB и bounds вычисляются из фактических outlines;
- vertical metrics обновляются либо сознательно удаляются только согласно config;
- `maxp`, `hhea`, `hmtx`, `loca` и `glyf` согласуются с новым glyph count;
- composite depth не превышает допустимый предел;
- переполнение signed/unsigned полей приводит к error.

### FR-FONT-005. Kerning и shaping source

В версии 1 word-glyph строится из базовых glyph advances без применения GPOS kerning внутри composite. Это соответствует текущей реализации. Опциональный режим `bakePositioning` может быть добавлен отдельно и должен использовать HarfBuzz positions для конкретного source sequence.

### FR-FONT-006. Имена

Конфигурация:

```yaml
font:
  family: "Project Shield"
  subfamily: "Regular"
  typographicFamily: "Project Shield"
  typographicSubfamily: "Regular"
  fullName: "Project Shield Regular"
  postScriptName: "ProjectShield-Regular"
  version: "1.0.0"
  uniqueId: "org.example.project-shield:1.0.0:<buildId>"
  description: "Modified shield font based on ..."
  copyright: "..."
  designer: "..."
  licenseDescription: "..."
  licenseUrl: "..."
```

Обновляются как минимум name IDs 0, 1, 2, 3, 4, 5, 6, 10, 11, 13, 14, 16, 17 и 18, если соответствующие значения заданы.

### FR-FONT-007. Reserved Font Name

Система не может юридически определить лицензионную допустимость, но обязана:

- извлечь license text/URL;
- обнаружить признаки OFL;
- предупредить при совпадении output family с source family;
- поддержать `licensePolicy: warn|error|ignore`;
- записать source attribution в manifest.

### FR-FONT-008. Удаляемые/пересчитываемые таблицы

- DSIG удаляется после модификации;
- stale checksums пересчитываются;
- `post` может быть сохранён или переведён в 3.0;
- vertical tables не удаляются без отчёта;
- таблицы variation удаляются после static instancing;
- неизвестные private tables сохраняются по default, если glyph count independence подтверждена policy; иначе warning/error.

### FR-FONT-009. Выходные форматы

Система выпускает только:

- `.ttf` — основной статический TrueType font;
- `.woff2` — web-контейнер, собранный из того же TrueType font и содержащий `glyf`.

Вывод `.otf`, CFF/CFF2 и конвертация outline flavor запрещены требованиями версии 1.

### FR-FONT-010. Neutral build

Система должна уметь создать neutral cut:

- новые name records;
- те же outlines/metrics;
- без shield lookup’ов;
- отдельная family или subfamily для использования на незакодированном тексте.

## 20. `shieldfont css build`

### FR-CSS-001

Генерирует CSS для всех faces:

```css
@font-face {
  font-family: "Project Shield";
  src: url("./ProjectShield-Regular.woff2") format("woff2");
  font-weight: 400;
  font-style: normal;
  font-display: block;
  font-synthesis: none;
}
```

### FR-CSS-002

Поддерживаемые параметры:

- relative/absolute asset base URL;
- cache-busting hash in filename;
- `font-display`;
- unicode-range generation per face;
- CSS classes;
- CSS custom properties;
- neutral class;
- SRI manifest отдельно от CSS.

### FR-CSS-003

CSS generator не должен включать TTF fallback по умолчанию для web delivery. TTF fallback включается отдельным флагом.

### FR-CSS-004

Для нескольких mappings/scopes возможны два режима:

1. один font file, содержащий все script-specific lookups;
2. отдельные font files и `unicode-range`.

Режим 1 — default, потому что OpenType ScriptList уже разделяет lookups. Режим 2 — оптимизация доставки и должен проверяться на корректный fallback.

## 21. `shieldfont codec build`

### FR-CODEC-001. Артефакты

```text
<Project>-codec.mjs
<Project>-codec.cjs
<Project>-codec.iife.js
<Project>-codec.d.ts
<Project>-mappings.json        # только при embed=false и явной публикации
```

### FR-CODEC-002. Public API

```ts
export interface CodecContext {
  locale?: string;
  script?: string;
  scope?: string;
  mappingId?: string;
}

export function encode(text: string, context?: CodecContext): string;
export function decode(text: string, context?: CodecContext): string;
export function encodeSegments(text: string, context?: CodecContext): Segment[];
export function decodeSegments(text: string, context?: CodecContext): Segment[];
export function resolveScope(context: CodecContext, text?: string): ScopeInfo;
export function listScopes(): ScopeInfo[];
export function verifyManifest(manifest: BuildManifest): VerificationResult;
```

### FR-CODEC-003. Выбор scope

Порядок:

1. explicit `scope`;
2. exact BCP 47 locale;
3. parent locale fallback;
4. configured Unicode script;
5. `DFLT` scope;
6. no-op/error согласно `unknownScopePolicy`.

Автоматическое распознавание естественного языка не является надёжным обязательным механизмом. Для language-specific dictionaries приложение должно передавать `locale` либо DOM `lang`.

### FR-CODEC-004. Tokenizer

Tokenizer должен:

- выполнять NFC;
- поддерживать Unicode letters и combining marks согласно выбранной token policy;
- не изменять HTML entities;
- иметь отдельные режимы `plain`, `html-text`, `markdown`, `dom-text-node`;
- пропускать code/pre/script/style/svg/math/textarea;
- сохранять byte-to-codepoint offsets для отчётов;
- иметь одинаковые fixture tests в Python и TypeScript.

### FR-CODEC-005. Case handling

Режим `auto`:

- lowercase;
- Titlecase первого cased code point;
- ALL CAPS;
- mixed case оставляется без подстановки по default.

Locale-sensitive casing должен использовать явный locale и тестироваться отдельно. Нельзя применять английскую модель регистра ко всем scripts.

### FR-CODEC-006. Decode

- `involution`: `decode` может использовать тот же mapping engine;
- `bidirectional`: используется inverse map;
- при collision inverse generation запрещается;
- decoder обязан повторять scope resolution encoder’а;
- `decode(encode(text, ctx), ctx) == normalized(text)` для всех поддержанных токенов.

### FR-CODEC-007. Browser exposure

По умолчанию:

```yaml
codec:
  embedMappings: false
  browserBuild: false
```

Публичный browser decoder раскрывает mapping и снижает стоимость обратного преобразования. Система должна предупреждать при `browserBuild=true` и записывать это в manifest/security report.

### FR-CODEC-008. Устранение дублирования

Standalone bundle должен собираться из того же TypeScript source, что package API. Ручное зеркалирование логики в shell heredoc, как в текущем проекте, в новой архитектуре запрещается.

## 22. `shieldfont verify`

Команда запускает уровни проверки.

### 22.1. Structural

- шрифт открывается `TTFont` в strict mode;
- корректны checksums;
- обязательные таблицы присутствуют;
- glyph order согласован;
- `maxp`, `hmtx`, `vmtx` при наличии, `loca` и `glyf` согласованы;
- name records валидны;
- PostScript name допустим;
- нет stale DSIG;
- WOFF2 повторно распаковывается;
- manifest hashes совпадают.

### 22.2. Layout inventory

- все scopes присутствуют в ScriptList/LangSys;
- `DFLT` оформлен как ScriptRecord;
- default language оформлен как DefaultLangSys;
- отсутствует незаконный LangSysRecord `dflt`;
- lookup indices валидны;
- context references валидны;
- lookup order соответствует plan.

### 22.3. Positive shaping

Для каждой пары и case variant:

- shaping target при заданных direction/script/language/features;
- ожидается output source composite `glyf`-glyph;
- advance и cluster mapping проверяются;
- тестируется начало/конец run, пробелы, punctuation, перенос text node.

HarfBuzz shaping зависит от properties buffer: direction, script, language и feature list. Проверка должна передавать их явно, а не полагаться на угадывание. [S7][S8]

### 22.4. Negative shaping

- target внутри более длинного слова не должен раскрываться;
- `latn` lookup не должен применяться под `cyrl`;
- `cyrl` lookup не должен применяться под `latn`;
- language-specific lookup не должен применяться в несовместимом LangSys;
- выключенный scope не должен срабатывать;
- source text под shield face должен вести себя согласно задокументированной involution policy;
- neutral face не должен выполнять shield substitutions.

### 22.5. Codec parity

- Python reference encoder vs TypeScript encoder;
- ESM vs CJS vs IIFE;
- source → encoded → decoded;
- corpus tests;
- property-based tests;
- HTML entities;
- combining marks;
- mixed scripts;
- locale fallback;
- prototype-pollution keys: `constructor`, `toString`, `__proto__`.

### 22.6. Browser

Playwright test page:

- шрифт реально загружен через `document.fonts`;
- shielded text имеет ожидаемые измерения;
- target не вспыхивает после successful load при выбранном display strategy;
- neutral text остаётся исходным;
- Chrome, Firefox, WebKit;
- optional screenshot diff.

### 22.7. Reports

```text
dist/reports/verify.json
dist/reports/verify.html
dist/reports/layout.json
dist/reports/browser.json
dist/reports/security.json
```

## 23. `shieldfont build`

Оркестратор выполняет DAG:

1. load config;
2. inspect source;
3. static instance;
4. normalize dictionaries;
5. validate scopes;
6. create output glyphs;
7. generate `.fea`;
8. compile GSUB;
9. apply names/metadata;
10. write sfnt;
11. write WOFF2;
12. build neutral face;
13. build CSS;
14. build codec;
15. verify;
16. write manifest/checksums;
17. publish to `dist` только после успешного Quality Gate.

Сборка выполняется во временном каталоге. Частично собранный `dist` не должен заменять предыдущий успешный output.

---

# Часть V. Конфигурация

## 24. Формат `shieldfont.yml`

```yaml
schema: "shieldfont/v1"

project:
  id: "example-project-shield"
  version: "1.0.0"
  outputDir: "dist"
  reproducible: true
  sourceDateEpoch: 1785888000

source:
  path: "fonts/Source.woff2"
  requiredOutline: "glyf"
  allowedContainers: ["ttf", "woff2"]
  instance:
    axes:
      wght: 400
      wdth: 100

font:
  family: "Example Project Shield"
  subfamily: "Regular"
  typographicFamily: "Example Project Shield"
  typographicSubfamily: "Regular"
  postScriptName: "ExampleProjectShield-Regular"
  version: "1.0.0"
  description: "Shielded derivative of Source Font"
  outputFormats: ["ttf", "woff2"]
  postTable: "keep-sfnt-drop-woff2"
  preserveExistingLayout: true
  neutralFace:
    enabled: true
    family: "Example Project Text"

layout:
  defaultFeature: "ccmp"
  boundaryMode: "fire-then-revert"
  maxEstimatedSubtableBytes: 40960
  useExtensionLookups: true
  defaultScopePolicy: "fallback"

scopes:
  - id: "default"
    encoder:
      locales: []
      sourceScripts: []
    shaping:
      openTypeScript: "DFLT"
      defaultLanguage: true
      languages: []
    dictionaries:
      - "dictionaries/default.csv"

  - id: "latin-en"
    encoder:
      locales: ["en"]
      sourceScripts: ["Latn"]
    shaping:
      targetScripts: ["Latn"]
      openTypeScript: "latn"
      defaultLanguage: true
      languages: []
    dictionaries:
      - "dictionaries/latin-en.csv"

  - id: "cyrillic-ru"
    encoder:
      locales: ["ru"]
      sourceScripts: ["Cyrl"]
    shaping:
      targetScripts: ["Cyrl"]
      openTypeScript: "cyrl"
      defaultLanguage: true
      languages: []
    dictionaries:
      - "dictionaries/cyrillic-ru.csv"

mapping:
  mode: "involution"
  duplicatePolicy: "error"
  targetCollisionPolicy: "error"
  selfMapPolicy: "drop-with-warning"
  crossScript: false
  caseMode: "auto"
  normalization: "NFC"

css:
  file: "example-shield.css"
  assetBaseUrl: "./fonts/"
  fontDisplay: "block"
  fontSynthesis: "none"
  classes:
    shield: "sf-shield"
    neutral: "sf-text"

codec:
  packageName: "@example/shield-codec"
  formats: ["esm", "cjs"]
  browserBuild: false
  embedMappings: false
  unknownScopePolicy: "no-op"

verification:
  levels: ["structural", "shaping", "codec", "browser"]
  harfbuzz:
    implementation: "both"
  browsers: ["chromium", "firefox", "webkit"]
  failOnWarning: false

license:
  policy: "warn"
```

## 25. Schema requirements

- JSON Schema публикуется вместе с CLI;
- unknown fields запрещены в strict mode;
- relative paths разрешаются относительно config file;
- environment interpolation выключена по default;
- secrets допускаются только через `${ENV:NAME}` в translation/LLM provider sections;
- resolved config сохраняется в manifest без secret values.

---

# Часть VI. Алгоритм генерации OpenType

## 26. Подготовка ruleset

Для каждого scope:

1. прочитать CSV;
2. NFC-normalизовать source/target;
3. применить case policy;
4. проверить target collision;
5. проверить glyph coverage;
6. определить target script;
7. построить `RuleId`;
8. отсортировать по длине target по убыванию;
9. сформировать canonical rules JSON;
10. вычислить `mappingHash`.

## 27. Создание source glyphs

Для rule `source → target` создать glyph variants:

```text
sf.<scopeHash>.<ruleHash>.lower
sf.<scopeHash>.<ruleHash>.title
sf.<scopeHash>.<ruleHash>.upper
```

Plaintext в glyph name запрещён.

Hash:

```text
SHA-256(buildSalt || NUL || scopeId || NUL || source || NUL || caseVariant)
```

Используются первые 80–96 бит. Collision внутри font проверяется; при collision длина hash увеличивается.

## 28. Word boundary: обязательная схема

Версия 1 обязана сохранить доказавшую практическую пригодность архитектуру fire-then-revert.

Для каждого scope:

```text
A: LigatureSubst target sequence -> source output glyph
B: SingleSubst optional one-glyph substitutions
C: MultipleSubst source output glyph -> target sequence
D: ChainContext letter-like BEFORE output glyph -> invoke C
E: ChainContext letter-like AFTER output glyph -> invoke C
```

Lookup C не подключается непосредственно к feature.

`letter-like` coverage определяется на основе Unicode Alphabetic/Letter policy и дополняется shield output glyphs, чтобы корректно отменять соседние подстановки внутри одного большого слова.

Односивольные правила должны иметь отдельную context policy; без неё любое однобуквенное правило опасно.

## 29. Script/LangSys attachment

Для каждого scope:

- создаётся или переиспользуется соответствующий ScriptRecord;
- если `defaultLanguage=true`, feature index добавляется в DefaultLangSys;
- каждый дополнительный OpenType language tag получает LangSysRecord;
- одинаковый lookup может быть подключён к нескольким language systems только явно;
- `DFLT` не смешивается с `latn/cyrl` без указанного fallback policy.

OpenType ScriptList выбирает feature data по script и language, а HarfBuzz учитывает script/language properties shaping buffer. [S1][S7][S9]

## 30. Компиляция `.fea`

Предпочтительный процесс:

1. сформировать AST через `fontTools.feaLib.ast`;
2. сериализовать стабильный `.fea`;
3. скомпилировать через `addOpenTypeFeatures()`;
4. выполнить post-compile layout audit;
5. при необходимости применить deterministic direct-table patch для lookup ordering/chunking;
6. повторно сериализовать таблицу и проверить HarfBuzz.

Использование AST предпочтительнее конкатенации строк, но output `.fea` остаётся читаемым и пригодным для независимой проверки.

## 31. Preservation existing GSUB

Стратегии:

- `merge` — default;
- `replace-feature` — заменить только заданный feature tag в выбранных scopes;
- `replace-all-gsub` — только explicit destructive mode.

В режиме `merge`:

- существующие FeatureRecords сохраняются;
- новые lookup’и выполняются до конфликтующих standard ligatures;
- все references после reorder валидируются;
- feature order и lookup order отражаются в report.

---

# Часть VII. Вспомогательные утилиты

## 32. `shieldfont translate`

### 32.1. Назначение

Переводит текстовые материалы с одного языка на другой, сохраняя структуру и выдавая provenance. Эта команда не должна автоматически строить shield mapping без отдельного этапа валидации.

### 32.2. Входы

- `.txt`;
- `.md`/`.mdx`;
- `.html`;
- `.json` по JSONPath;
- `.csv` по выбранным columns;
- stdin.

### 32.3. Требования

- `--source-locale`, `--target-locale`;
- сохранение placeholders: `{name}`, `%s`, `${value}`, ICU messages;
- сохранение URLs, code spans, tags и entities;
- glossary;
- do-not-translate list;
- batch processing;
- retry/backoff;
- local cache по content hash;
- dry-run;
- diff report;
- deterministic segmentation;
- human-review status.

### 32.4. Providers

Интерфейс:

```python
class TranslatorProvider(Protocol):
    def translate(self, segments, source_locale, target_locale, glossary, options): ...
```

Обязательные реализации первой версии:

- `mock` для tests;
- `openai-compatible`;
- `http-json` generic adapter;
- `local-command` для локального переводчика.

Конкретные облачные провайдеры могут подключаться отдельными extras.

### 32.5. Выход

```text
translated/<locale>/...
reports/translation-<locale>.json
```

Provenance:

- provider;
- model;
- endpoint hash без secret;
- prompt template version;
- temperature/top_p;
- timestamp;
- source hash;
- glossary hash;
- segments count;
- warnings.

## 33. `shieldfont dict from-text`

### 33.1. Назначение

Формирует черновой shield dictionary из предоставленного корпуса.

### 33.2. Этапы

1. Extract visible text;
2. Unicode normalization;
3. language/script segmentation;
4. tokenization and frequency count;
5. filtering stopwords/length/protected terms;
6. morphology/POS tagging через plugin;
7. grouping by grammatical/morphological buckets;
8. LLM generation of target candidates;
9. deterministic validation;
10. semantic-distance/identity veto plugin;
11. construction of injective or involutive pairs;
12. coverage simulation on corpus;
13. human review;
14. export approved CSV.

### 33.3. LLM не является валидатором

Ответ LLM считается только candidate set. Финальное правило допускается в approved CSV только после детерминированных проверок:

- schema valid;
- source/target differ;
- script policy;
- glyph coverage;
- target uniqueness;
- case compatibility;
- token boundary safety;
- no deny-listed content;
- no placeholder/markup;
- round-trip feasibility;
- human approval, если `requireReview=true`.

### 33.4. Структурированный ответ LLM

```json
{
  "source": "...",
  "candidates": [
    {
      "target": "...",
      "pos": "noun",
      "morphology": "...",
      "rationale": "...",
      "confidence": 0.0
    }
  ]
}
```

`confidence` модели не используется как доказательство корректности; это только ranking hint.

### 33.5. Pairing

Для involution:

- candidate graph строится по bucket;
- запрещённые edges удаляются;
- применяется maximum-cardinality matching;
- seed управляет только детерминированным tie-breaking;
- непарные слова остаются открытыми;
- отчёт показывает dropped/unpaired words.

### 33.6. Human review

Команда создаёт:

```text
dictionaries/generated/<scope>.candidates.csv
dictionaries/generated/<scope>.review.html
dictionaries/generated/<scope>.approved.csv
```

Статусы:

```text
candidate
approved
rejected
needs-review
```

Build использует только `approved` либо отдельный CSV без status column.

---

# Часть VIII. Manifest, воспроизводимость и безопасность

## 34. Build manifest

`dist/manifest.json`:

```json
{
  "schema": "shieldfont-build/v1",
  "projectId": "example-project-shield",
  "projectVersion": "1.0.0",
  "toolVersion": "1.0.0",
  "buildId": "sha256:...",
  "source": {
    "path": "fonts/Source.woff2",
    "sha256": "...",
    "outlineType": "glyf",
    "faceIndex": 0,
    "instance": {"wght": 400}
  },
  "font": {
    "family": "Example Project Shield",
    "postScriptName": "ExampleProjectShield-Regular"
  },
  "scopes": [
    {
      "id": "latin-en",
      "mappingHash": "sha256:...",
      "pairs": 1200,
      "openTypeScript": "latn",
      "defaultLanguage": true
    }
  ],
  "artifacts": [
    {"path": "fonts/ExampleProjectShield-Regular.woff2", "sha256": "..."}
  ],
  "verification": {
    "status": "pass",
    "report": "reports/verify.json"
  },
  "security": {
    "browserDecoderIncluded": false,
    "mappingEmbedded": false,
    "glyphNamesDroppedFromWoff2": true
  }
}
```

## 35. Reproducible build

При `reproducible=true`:

- timestamps берутся из `sourceDateEpoch`;
- input ordering стабилен;
- YAML resolved deterministically;
- JSON keys/rows стабильно сортируются;
- случайные salts запрещены без сохранённого seed;
- output compression parameters фиксированы;
- абсолютные paths не записываются;
- build сравнивается повторным запуском в CI.

## 36. Security report

Должен явно сообщать:

- mapping можно восстановить из раздаваемого font file;
- browser decoder или embedded mapping дополнительно упрощает восстановление;
- механизм не защищает от OCR/headless rendering;
- `post` format 3 удаляет glyph names, но не скрывает GSUB/outline semantics;
- private mapping препятствует только повторному использованию заранее известного словаря;
- plaintext не должен попадать в client bundle до кодирования.

## 37. Лицензирование

Система должна отделять:

- лицензию toolchain code;
- лицензию source font;
- лицензию derived font;
- право на изменение и распространение;
- Reserved Font Name requirements.

Toolchain не выдаёт юридическое заключение. Он формирует warnings и attribution report.

---

# Часть IX. Ошибки, логирование и API

## 38. Формат логов

Режимы:

```text
--log-format text
--log-format json
--quiet
--verbose
--trace
```

JSON event:

```json
{
  "time": "2026-08-05T00:00:00Z",
  "level": "error",
  "code": "SF-DICT-TARGET-COLLISION",
  "stage": "dictionary.validate",
  "scope": "latin-en",
  "file": "dictionaries/latin.csv",
  "line": 42,
  "message": "Target is produced by multiple sources",
  "details": {"target": "...", "sources": ["...", "..."]}
}
```

## 39. Exit codes

| Code | Значение |
|---:|---|
| 0 | success |
| 1 | generic failure |
| 2 | invalid CLI/config |
| 10 | source font error |
| 11 | неподдерживаемый контейнер либо отсутствие TrueType `glyf` |
| 20 | dictionary parse error |
| 21 | dictionary semantic conflict |
| 30 | feature generation error |
| 31 | GSUB compile/offset error |
| 40 | font serialization error |
| 50 | shaping verification failure |
| 51 | codec parity failure |
| 52 | browser verification failure |
| 60 | translation provider failure |
| 61 | LLM output validation failure |
| 70 | licensing policy failure |

## 40. Python API

Публичные классы:

```python
ShieldFontProject
BuildConfig
SourceFontInfo
DictionaryRule
DictionaryScope
NormalizedRuleset
FeaturePlan
FontBuildResult
VerificationReport
BuildManifest
TranslatorProvider
DictionaryCandidateProvider
```

Публичные методы должны быть документированы и типизированы. CLI tests не заменяют API tests.

---

# Часть X. Производительность

## 41. Требования

Поскольку скорость зависит от сложности TrueType outlines и числа pairs, приёмка задаётся на эталонных fixtures, а не как универсальная цифра.

Обязательные benchmark fixtures:

- 500 pairs;
- 2 000 pairs;
- 5 000 pairs;
- 12 000 pairs;
- `latn` only;
- `cyrl` only;
- mixed `DFLT+latn+cyrl`;
- static TrueType;
- variable TrueType после instancing;
- WOFF2 с `glyf`.

Метрики:

- parse time;
- glyph construction time;
- feature generation time;
- feature compile time;
- WOFF2 compression time;
- peak RSS;
- output size;
- shaping verification time.

Regression threshold задаётся в CI относительно зафиксированного baseline и reference runner.

## 42. Оптимизации

- кешировать cmap;
- кешировать разобранные TrueType outlines и метрики компонентов;
- строить glyphs в deterministic worker pool, но сериализовать в стабильном порядке;
- chunk GSUB до компиляции;
- incremental cache по source hash + scope mapping hash;
- не перезапускать browser tests, если font/CSS hash не изменился;
- поддержать content-scoped subsetting отдельной командой версии 1.1.

---

# Часть XI. Тестовая стратегия

## 43. Unit tests

### Python

- CSV parser;
- NFC;
- collisions;
- involution;
- scope resolver;
- script classification;
- names;
- hash names;
- glyf metrics;
- составные `glyf`-глифы и их метрики;
- `.fea` AST;
- manifest;
- reproducibility.

### TypeScript

- tokenizer;
- entities;
- case handling;
- locale fallback;
- script fallback;
- encode/decode;
- prototype keys;
- mapping loading;
- package format parity.

## 44. Integration tests

Fixtures:

1. Minimal Latin TTF;
2. Minimal Cyrillic TTF;
3. Mixed Latin/Cyrillic TTF;
4. WOFF2 с `glyf`;
5. variable TTF с `glyf/gvar`;
6. variable WOFF2 с TrueType outlines;
7. source with existing `liga`, `calt`, `ccmp`;
8. source with vertical tables;
9. malformed TTF;
10. malformed WOFF2;
11. WOFF2/CFF negative fixture;
12. OTF/CFF negative fixture.

## 45. Golden tests

- generated `.fea`;
- resolved config;
- canonical CSV/JSON;
- manifest;
- CSS;
- TypeScript declarations;
- selected TTX excerpts.

Binary font golden hash допускается только в reproducible fixtures.

## 46. Adversarial tests

- many-to-one target;
- cyclic mapping length >2;
- duplicate CSV headers;
- embedded NUL;
- bidi controls;
- homoglyphs;
- combining sequences;
- extremely long word;
- target prefix of another target;
- source/target across scripts;
- script without OpenType tag mapping;
- GSUB near 64 KiB boundaries;
- existing Extension lookups;
- broken context references;
- HTML entities;
- mixed-script identifiers;
- strings `constructor`, `toString`, `__proto__`.

---

# Часть XII. Критерии приёмки

## 47. Общий сценарий

Команда:

```bash
shieldfont build --config shieldfont.yml
```

с валидными inputs должна создать атомарно:

```text
dist/
  fonts/
    <name>.ttf
    <name>.woff2
    <neutral>.woff2
  features/
    <name>.fea
    <name>.layout.json
  maps/
    <scope>.csv
    <scope>.json
    <scope>.inverse.json
  css/
    <name>.css
  codec/
    <name>-codec.mjs
    <name>-codec.cjs
    <name>-codec.d.ts
  reports/
    inspect.json
    dictionaries.json
    layout.json
    verify.json
    verify.html
    security.json
    license.json
  manifest.json
  SHA256SUMS
```

## 48. Функциональная приёмка

### AC-001

Static TTF с `glyf` собирается в TTF и WOFF2.

### AC-002

WOFF2 с `glyf` автоматически распаковывается и собирается обратно в согласованные TTF и WOFF2.

### AC-003

Variable TrueType input после выбора instance собирается в static TTF и WOFF2; variation tables в результате отсутствуют.

### AC-004

Output family, subfamily, PostScript name и version совпадают с config и видны через независимый inspector.

### AC-005

Разные CSV для `DFLT`, `latn`, `cyrl` создают независимые lookup groups.

### AC-006

Latin target раскрывается под `latn`; Cyrillic target — под `cyrl`; отрицательные cross-script tests проходят.

### AC-007

Default scope подключён как `DFLT` ScriptRecord и DefaultLangSys; незаконный LangSysRecord `dflt` отсутствует.

### AC-008

Каждая approved mapping pair проходит lower/title/upper shaping tests согласно case policy.

### AC-009

Короткие target не срабатывают внутри более длинных буквенных токенов.

### AC-010

Существующие source-font features сохраняются и проходят regression fixtures.

### AC-011

GSUB с 12 000 pairs компилируется без offset overflow на эталонном fixture.

### AC-012

JS `decode(encode(text, ctx), ctx)` возвращает NFC-нормализованный source для corpus каждого scope.

### AC-013

Python reference и все JS bundles дают одинаковый output.

### AC-014

CSS загружает WOFF2 в Chromium, Firefox и WebKit.

### AC-015

Neutral face не содержит shield substitutions.

### AC-016

При target collision build завершается до публикации `dist`.

### AC-017

При font/mapping mismatch verify завершается ошибкой.

### AC-018

Два reproducible builds имеют одинаковые SHA-256 для всех артефактов.

### AC-019

Translation utility сохраняет placeholders/tags на test corpus.

### AC-020

LLM dictionary generator не переносит candidate в approved output без deterministic validation и требуемого review status.

## 49. Документационная приёмка

Должны быть опубликованы:

- installation guide;
- configuration reference;
- CSV specification;
- OpenType architecture note;
- custom font guide;
- scope/language guide;
- codec API reference;
- threat model;
- licensing guide;
- migration guide с текущего `generate_font.py`;
- troubleshooting;
- examples `DFLT`, `latn`, `cyrl`, mixed.

---

# Часть XIII. Этапы реализации и Quality Gates

## Этап 0. Фиксация поведения текущей реализации

Работы:

- перенести ключевые fixtures из текущего проекта;
- зафиксировать fire-then-revert tests;
- зафиксировать large GSUB tests;
- зафиксировать encoder edge cases;
- сформировать architecture decision records.

**QG-0:** все перенесённые tests воспроизводят текущее поведение; известные расхождения документированы.

## Этап 1. Core model, config, dictionaries

Работы:

- Pydantic models;
- YAML/JSON Schema;
- CSV parser/normalizer;
- scope model;
- collisions/involution;
- canonical ruleset;
- manifest skeleton.

**QG-1:** AC-016, canonical output и reproducibility unit tests проходят.

## Этап 2. Font inspect/normalize

Работы:

- TTF/WOFF2 inspect;
- проверка обязательной таблицы `glyf`;
- variable TrueType instancing;
- names/license inventory;
- unpack;
- отклонение CFF/CFF2 и неподдерживаемых контейнеров.

**QG-2:** валидные TrueType fixtures успешно inspect’ятся; malformed и CFF/CFF2 fixtures отклоняются.

## Этап 3. TrueType glyph builder и feature compiler

Работы:

- composite glyph factory;
- `.fea` AST;
- fire-then-revert;
- DFLT/latn/cyrl scopes;
- lookup chunking;
- merge existing GSUB.

**QG-3:** AC-001–AC-003 и AC-005–AC-011 проходят на TrueType fixtures.

## Этап 4. CSS, neutral face, codec

Работы:

- CSS generator;
- neutral face;
- TypeScript registry;
- ESM/CJS/IIFE build;
- Python/JS parity;
- scope selection.

**QG-4:** AC-012–AC-015 проходят.

## Этап 5. Verification and CI

Работы:

- structural audit;
- HarfBuzz audit;
- browser tests;
- HTML report;
- reproducible build job;
- performance baseline.

**QG-5:** AC-017–AC-018 и полный CI matrix проходят.

## Этап 6. Translation utility

**QG-6:** placeholders/tags/glossary/cache tests проходят; provider failures не повреждают output.

## Этап 7. LLM dictionary generator

**QG-7:** candidate/approved separation, deterministic validator, review workflow и provenance проходят.

## Этап 8. Migration and release

Работы:

- compatibility importer для текущих JSON mappings;
- wrapper для старого CLI;
- migration docs;
- release packages;
- sample projects.

**QG-8:** существующий English mapping собирается новым toolchain и проходит эквивалентный audit.

---

# Часть XIV. Миграция текущего репозитория

## 50. Что следует переиспользовать

1. Fire-then-revert алгоритм.
2. Chunking больших LigatureSubst/MultipleSubst.
3. Coverage sorting по glyph ID.
4. Проверку `lsb == xMin` для glyf composites.
5. Salted opaque glyph names и `post` format 3 для web.
6. NFC/tokenizer/entity edge cases.
7. Инъективность mapping.
8. Font+mapping single-source-of-truth.
9. Subsetting architecture как будущий модуль.
10. HarfBuzz audit patterns.

## 51. Что следует переработать

1. Разделить 65-KB `generate_font.py` на библиотечные модули.
2. Заменить один глобальный JSON mapping на scope registry.
3. Зафиксировать единый TrueType-only builder и раннее отклонение шрифтов без `glyf`.
4. Сделать `.fea` обязательным артефактом.
5. Устранить ручную копию encoder logic в shell script.
6. Ввести единую version/build metadata.
7. Отделить browser decoder от server/build encoder.
8. Перевести warnings об auto-drop mappings в strict configurable policy.
9. Объединить отдельные Python scripts единым CLI.
10. Добавить machine-readable errors и manifest.

## 52. Совместимость

Команда:

```bash
shieldfont migrate legacy-project \
  --mapping scripts/v18alpha_for_font.json \
  --font path/to/base.ttf \
  --out migrated/
```

должна создать:

- CSV из flat JSON;
- `shieldfont.yml` с `DFLT`/`latn` scope;
- сохранённый mapping ID;
- migration report;
- список несовместимостей.

---

# Часть XV. Риски

## 53. Основные технические риски

### RISK-01. OpenType offset overflow

Мера: deterministic chunking, extension lookups, preflight size estimation, large fixtures.

### RISK-02. Ошибочное разделение script/language

Мера: отдельные encoder locale и shaping OpenType fields; negative tests; explicit context API.

### RISK-03. Повреждённые или нестандартные TrueType tables

Мера: strict inspection, проверка `glyf/loca/maxp/hmtx`, независимый HarfBuzz audit и negative fixtures.

### RISK-04. Mapping/font drift

Мера: mappingHash в name/meta/manifest, atomic deployment, verify API.

### RISK-05. Browser decoder раскрывает mapping

Мера: disabled by default, security warning, server/build encoder package отдельно.

### RISK-06. Неправильная Unicode case handling

Мера: locale-aware casing policy, mixed-case no-op, corpus tests.

### RISK-07. Cross-script target меняет shaping script

Мера: targetScript — отдельное обязательное поле для cross-script mode.

### RISK-08. Лицензия исходного font

Мера: metadata inventory, reserved-name warning, policy gate, attribution report.

### RISK-09. LLM создаёт грамматически или семантически плохие пары

Мера: LLM only candidate generator, deterministic validators, review requirement.

### RISK-10. Размер web-font

Мера: per-script unicode-range mode и последующий content-aware subsetting; mapping должен урезаться синхронно.

---

# Часть XVI. Минимальные примеры

## 54. CSV

`dictionaries/latin-en.csv`:

```csv
source,target,case_mode,priority,comment
future,season,auto,100,"noun-like replacement"
writing,reading,auto,100,"gerund"
protect,expose,auto,100,"verb"
```

`dictionaries/cyrillic-ru.csv`:

```csv
source,target,case_mode,priority,comment
будущее,прошлое,auto,100,"существительное"
защищает,раскрывает,auto,100,"глагол"
текст,архив,auto,100,"существительное"
```

Для `mappingMode: involution` в CSV должны присутствовать обе стороны либо normalizer должен получить explicit permission `completeInvolution: true` и сгенерировать обратные строки с отметкой origin.

## 55. Упрощённый `.fea`-фрагмент

```fea
languagesystem DFLT dflt;
languagesystem latn dflt;
languagesystem cyrl dflt;

lookup SF_latin_en_LIG_000 useExtension {
  sub s e a s o n by sf.a1b2c3.lower;
} SF_latin_en_LIG_000;

lookup SF_latin_en_REVERT_000 useExtension {
  sub sf.a1b2c3.lower by s e a s o n;
} SF_latin_en_REVERT_000;

feature ccmp {
  script latn;
  language dflt;
  lookup SF_latin_en_LIG_000;
  lookup SF_latin_en_CTX_BEFORE;
  lookup SF_latin_en_CTX_AFTER;

  script cyrl;
  language dflt;
  lookup SF_cyrillic_ru_LIG_000;
  lookup SF_cyrillic_ru_CTX_BEFORE;
  lookup SF_cyrillic_ru_CTX_AFTER;
} ccmp;
```

Примечание: окончательный синтаксис context rules должен генерироваться AST и проверяться feaLib; fragment показывает структуру, а не полный production output.

## 56. JS

```ts
import { encode, decode } from "@example/shield-codec";

const encodedRu = encode("Будущее защищает текст", { locale: "ru" });
const originalRu = decode(encodedRu, { locale: "ru" });

const encodedEn = encode("The future protects writing", { locale: "en" });
```

Для HTML build:

```ts
const encoded = encode(sourceText, { locale: page.locale });
const html = `<p class="sf-shield" lang="${page.locale}">${escapeHtml(encoded)}</p>`;
```

Кодирование выполняется до отправки plaintext в browser bundle.

---

# Часть XVII. Итоговое архитектурное решение

Новый toolchain следует строить не как расширение одного монолитного `generate_font.py`, а как связку:

1. **Python TrueType engineering core** — разбор TTF/WOFF2, `glyf`-глифы, feature plan, compilation и verification;
2. **Canonical ruleset/manifest** — единый контракт между всеми этапами;
3. **TypeScript codec** — scope-aware encoding/decoding, сгенерированный из canonical ruleset;
4. **Build orchestrator** — атомарная сборка всех артефактов;
5. **Optional language services** — translation и LLM dictionary generation, не участвующие в воспроизводимой сборке без заранее утверждённых outputs.

Ключевой инженерный принцип: выбор mapping в JS и выбор OpenType lookup при shaping должны быть двумя реализациями одной и той же scope-модели. Без этого многоязычный шрифт будет периодически показывать target-текст вместо source либо применять словарь другого языка.

---

# Источники анализа репозитория

- **[R1]** README: https://github.com/alexeydott/shieldfont/blob/d6efb2d3972569628e870ff2767cd29412c245ee/README.md
- **[R2]** Root tree: https://github.com/alexeydott/shieldfont/tree/d6efb2d3972569628e870ff2767cd29412c245ee
- **[R3]** GitHub languages API: https://api.github.com/repos/alexeydott/shieldfont/languages
- **[R4]** Root package.json: https://github.com/alexeydott/shieldfont/blob/d6efb2d3972569628e870ff2767cd29412c245ee/package.json
- **[R5]** Core package.json: https://github.com/alexeydott/shieldfont/blob/d6efb2d3972569628e870ff2767cd29412c245ee/packages/core/package.json
- **[R6]** Core encoder: https://github.com/alexeydott/shieldfont/blob/d6efb2d3972569628e870ff2767cd29412c245ee/packages/core/src/encode.ts
- **[R7]** React package.json: https://github.com/alexeydott/shieldfont/blob/d6efb2d3972569628e870ff2767cd29412c245ee/packages/react/package.json
- **[R8]** React sources: https://github.com/alexeydott/shieldfont/tree/d6efb2d3972569628e870ff2767cd29412c245ee/packages/react/src
- **[R9]** Font package.json: https://github.com/alexeydott/shieldfont/blob/d6efb2d3972569628e870ff2767cd29412c245ee/packages/font/package.json
- **[R10]** CSS: https://github.com/alexeydott/shieldfont/blob/d6efb2d3972569628e870ff2767cd29412c245ee/packages/font/shieldfont.css
- **[R11]** Python requirements: https://github.com/alexeydott/shieldfont/blob/d6efb2d3972569628e870ff2767cd29412c245ee/requirements.txt
- **[R12]** Custom mappings: https://github.com/alexeydott/shieldfont/blob/d6efb2d3972569628e870ff2767cd29412c245ee/docs/custom-mappings.md
- **[R13]** Scripts tree: https://github.com/alexeydott/shieldfont/tree/d6efb2d3972569628e870ff2767cd29412c245ee/scripts
- **[R14]** CI: https://github.com/alexeydott/shieldfont/blob/d6efb2d3972569628e870ff2767cd29412c245ee/.github/workflows/test.yml
- **[R15]** `generate_font.py`, CLI and setup: https://github.com/alexeydott/shieldfont/blob/d6efb2d3972569628e870ff2767cd29412c245ee/scripts/generate_font.py
- **[R16]** `generate_font.py`, build/output section: тот же файл
- **[R17]** `generate_font.py`, composite glyph and fire-then-revert: тот же файл
- **[R18]** `generate_font.py`, glyph-name privacy: тот же файл
- **[R19]** `generate_font.py`, GSUB lookup construction and attachment: тот же файл
- **[R20]** Custom faces: https://github.com/alexeydott/shieldfont/blob/d6efb2d3972569628e870ff2767cd29412c245ee/docs/custom-faces.md
- **[R21]** Standalone encoder: https://github.com/alexeydott/shieldfont/blob/d6efb2d3972569628e870ff2767cd29412c245ee/packages/font/shieldfont-encoder.js
- **[R22]** CDN encoder build: https://github.com/alexeydott/shieldfont/blob/d6efb2d3972569628e870ff2767cd29412c245ee/scripts/build-encoder-cdn.sh
- **[R23]** Font audit: https://github.com/alexeydott/shieldfont/blob/d6efb2d3972569628e870ff2767cd29412c245ee/scripts/audit_font.py
- **[R24]** Subsetting: https://github.com/alexeydott/shieldfont/blob/d6efb2d3972569628e870ff2767cd29412c245ee/scripts/subset_font.py

# Нормативные и первичные технические источники

- **[S1]** OpenType 1.9.1 Script tags: https://learn.microsoft.com/en-us/typography/opentype/spec/scripttags
- **[S2]** OpenType 1.9.1 Language system tags: https://learn.microsoft.com/en-us/typography/opentype/spec/languagetags
- **[S3]** fontTools `TTFont`: https://fonttools.readthedocs.io/en/latest/ttLib/ttFont.html
- **[S4]** fontTools WOFF2: https://fonttools.readthedocs.io/en/stable/ttLib/woff2.html
- **[S5]** fontTools feaLib: https://fonttools.readthedocs.io/en/latest/feaLib/index.html
- **[S6]** Adobe OpenType Feature File Specification: https://adobe-type-tools.github.io/feature_file_change_review/OpenTypeFeatureFileSpecification_diff.html
- **[S7]** HarfBuzz `hb-shape`: https://harfbuzz.github.io/harfbuzz-hb-shape.html
- **[S8]** HarfBuzz shaping and shape plans: https://harfbuzz.github.io/shaping-and-shape-plans.html
- **[S9]** HarfBuzz OpenType features: https://harfbuzz.github.io/shaping-opentype-features.html

