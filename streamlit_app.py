from pathlib import Path

import streamlit as st

from app.resume_tailor import tailor_resume


UPLOAD_DIR = Path("uploads")
OUTPUT_DIR = Path("artifacts")


def _save_upload(file_obj: object, prefix: str) -> str:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    name = getattr(file_obj, "name", "upload.txt")
    target = UPLOAD_DIR / f"{prefix}_{name}"
    target.write_bytes(file_obj.getbuffer())
    return target.as_posix()


def main() -> None:
    st.set_page_config(page_title="AI Resume Builder", layout="wide")
    st.title("AI Resume Builder")
    st.caption("Upload a resume and a job description to generate a tailored resume.")

    col1, col2 = st.columns(2)
    with col1:
        resume_file = st.file_uploader("Resume file", type=["txt", "md", "html", "htm", "pdf"])
    with col2:
        jd_file = st.file_uploader("Job description file", type=["txt", "md", "html", "htm", "pdf"])

    if st.button("Generate Tailored Resume", use_container_width=True):
        if not resume_file or not jd_file:
            st.error("Upload both resume and JD files.")
        else:
            resume_path = _save_upload(resume_file, "resume")
            jd_path = _save_upload(jd_file, "jd")
            result = tailor_resume(resume_path=resume_path, jd_path=jd_path, output_dir=OUTPUT_DIR.as_posix())
            st.session_state["tailor_result"] = result

    result = st.session_state.get("tailor_result")
    if not result:
        return
    if not result.get("ok"):
        st.error(str(result.get("error", "Tailoring failed.")))
        return

    st.success(f"Done using `{result.get('mode')}` mode.")
    summary = result.get("change_summary", [])
    if summary:
        st.subheader("Change Summary")
        for item in summary:
            st.write(f"- {item}")
    notes = result.get("notes")
    if notes:
        st.caption(str(notes))

    output_path = Path(str(result.get("output_path", "")))
    if output_path.exists():
        st.download_button(
            "Download Tailored Resume",
            data=output_path.read_bytes(),
            file_name=output_path.name,
            mime="application/octet-stream",
            use_container_width=True,
        )
    if not result.get("format_preserved", True):
        st.warning("Original extension was not preserved for output.")


if __name__ == "__main__":
    main()
