# Raw Event + Tracking Coaching Dashboard

Static dashboard generated from raw Opta F24/F7 XML and raw Tracab tracking frames.

Data scope:

- Match: Manchester City 3-1 Manchester United, Premier League 2018-19 GW12
- Event source: raw Opta F24 XML
- Lineup source: raw Opta F7 XML
- Tracking source: raw Tracab `.dat` frame stream
- Excluded: provider aggregate tables, prior model outputs, previous project reports, skeleton data

Run locally:

```bash
python3 scripts/build_dashboard_data.py
python3 -m http.server 5173
```

Open `http://localhost:5173`.
