import streamlit as st
import streamlit.components.v1 as components

st.segmented_control("Test", ["A", "B", "C"], key="my_seg")

components.html("""
<script>
setTimeout(function() {
    var seg = window.parent.document.querySelector('[data-testid="stSegmentedControl"]');
    if (seg) {
        var html = seg.outerHTML;
        fetch("http://localhost:8000/dump", {
            method: "POST",
            body: html
        });
    }
}, 2000);
</script>
""", height=0)
