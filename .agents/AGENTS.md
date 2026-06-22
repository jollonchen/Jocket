# Jocket Design Guidelines

## Layout & Container Aesthetics

- **No Double-Container visuals for interactive controls/buttons/textboxes**: Do not wrap buttons or other input fields in a secondary bordered/colored container. If a system-generated wrapper exists (e.g. Streamlit's nested divs), make the outer container transparent (no border, no background, no shadow) if the inner elements are already containerized, or vice-versa. Never present stacked container aesthetics to the user.
