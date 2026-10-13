# Countess 3 / 3 FL CSV export: column definition

Source: Thermo Fisher MAN0019567, *Countess 3 FL Automated Cell Counter User Guide*,
Appendix E "CSV file format definition" (pages 81–84). No public example file was
found; this table is the basis for the LIMS parser and its synthetic test fixture.
One row per count. Columns are listed in spreadsheet order.

## Columns the LIMS should import

| Col | Column name | Maps to attribute |
|---|---|---|
| A | Count ID | source record reference |
| B | Session ID | source record reference |
| C | Sample name | matched against the tube ID (confirm step) |
| D | Date & Time | measurement time |
| E | Count mode | BF-based or FL-based |
| F | Type | BF-Brightfield or FL-Fluorescence |
| G | Trypan blue corrected | yes/no |
| H | Pre-Dilution corrected | yes/no |
| I | Total concentration | concentration (cells/mL) |
| J | Total cells counted | |
| K | Live concentration | |
| L | Live cells counted | |
| M | Dead concentration | |
| N | Dead cells counted | |
| O | Viability (%) | viability % |
| P | Live average size (µm) | |
| Q | Dead average size (µm) | |
| BR | Software revision | provenance |
| BS | Aggregation(%) | |

## Fluorescence columns (Countess 3 FL only; blank on brightfield counts)

R Cube 1 name · S Cube 1 concentration · T Cube 1 (%) · U Cube 1 cells counted ·
V Cube 2 name · W Cube 2 concentration · X Cube 2 (%) · Y Cube 2 cells counted ·
Z Cube 1+2 concentration · AA Cube 1+2 (%) · AB Cube 1+2 cells counted ·
AC Cube 1 average Size (µm) · AD Cube 2 average Size (µm)

## Instrument / gating settings (store with the attachment, not as attributes)

AE Focus value · AF Focus motor value · AG BF light intensity · AH BF LED intensity ·
AI Live size min · AJ Live size max · AK Live brightness min · AL Live brightness max ·
AM Live circularity min · AN Live circularity max · AO Dead size min · AP Dead size max ·
AQ Dead brightness min · AR Dead brightness max · AS Dead circularity min · AT Dead circularity max ·
AU Cube 1 light intensity · AV Cube 1 LED intensity · AW Cube 2 light intensity · AX Cube 2 LED intensity ·
AY BF size min · AZ BF size max · BA BF brightness min · BB BF brightness max ·
BC BF circularity min · BD BF circularity max · BE–BP Cube 1 / Cube 2 brightness, size, circularity min/max

Notes
- When gates are fully open the CSV shows 0–70 for cell size and 0–255 for brightness (troubleshooting appendix).
- The guide's own table has typos in BG–BJ descriptions; treat the column *names* as authoritative.
- A CSV export can contain Current Count, Session, Today, Yesterday, Previous 7 days, Previous 30 days, or All counts, so the parser must handle many rows and let the user pick the right one per tube.
- The Countess II / II FL guide (Appendix D) describes the older format; it is not reproduced here. Verify column order against a real export before trusting the parser on an older instrument.
