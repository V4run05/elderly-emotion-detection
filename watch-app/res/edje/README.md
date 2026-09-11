The current UI (single label + single "Check in" button) is built directly in `src/main.c` via EFL
widgets (`elm_label_add` / `elm_button_add`), so no custom `.edc`/`.edj` layout is required for the first
working version. Add an `.edc` file here if a custom watch-face-style layout is needed later.
