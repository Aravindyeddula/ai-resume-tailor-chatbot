from pathlib import Path
import os

import streamlit as st

from app.latex_resume import generate_latex_resume_from_file
from app.resume_tailor import tailor_resume_with_jd_text


UPLOAD_DIR = Path("uploads")
OUTPUT_DIR = Path("artifacts")


def _save_resume_upload(file_obj: object) -> str:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    name = getattr(file_obj, "name", "resume.pdf")
    target = UPLOAD_DIR / name
    target.write_bytes(file_obj.getbuffer())
    return target.as_posix()


def main() -> None:
    st.set_page_config(page_title="AI Resume Builder", layout="wide")
    st.title("AI Resume Builder")
    st.caption("Upload your resume file from local system and paste the target job description text.")
    st.caption("Build: 2026-02-19-openai-strict")

    resume_file = st.file_uploader(
        "Upload Resume File",
        type=["pdf", "docx", "txt", "md", "html", "htm"],
        help="Supported: PDF, DOCX, TXT, MD, HTML, HTM",
    )
    jd_text = st.text_area(
        "Paste Job Description",
        height=260,
        placeholder="Paste the target job description here...",
    )
    require_openai = st.checkbox("Require OpenAI rewrite (no heuristic fallback)", value=True)

    with st.expander("Runtime Diagnostics", expanded=False):
        key = os.getenv("OPENAI_API_KEY", "")
        st.write(f"OPENAI_API_KEY detected: `{bool(key)}`")
        st.write(f"Python executable: `{os.sys.executable}`")

    c1, c2 = st.columns(2)
    generate_tailored = c1.button("Generate Tailored Resume", use_container_width=True)
    generate_latex = c2.button("Generate LaTeX Resume (.tex)", use_container_width=True)

    if generate_tailored or generate_latex:
        if not resume_file:
            st.error("Please upload your resume file.")
            return
        if not jd_text.strip():
            st.error("Please paste a job description.")
            return
        if require_openai and not os.getenv("OPENAI_API_KEY", "").strip():
            st.error("OpenAI key is not available in this Streamlit process. Set OPENAI_API_KEY and restart app.")
            return
        resume_path = _save_resume_upload(resume_file)

        if generate_tailored:
            result = tailor_resume_with_jd_text(
                resume_path=resume_path,
                jd_text=jd_text,
                output_dir=OUTPUT_DIR.as_posix(),
            )
            st.session_state["tailor_result"] = result

        if generate_latex:
            latex_result = generate_latex_resume_from_file(
                resume_path=resume_path,
                jd_text=jd_text,
                output_dir=OUTPUT_DIR.as_posix(),
            )
            st.session_state["latex_result"] = latex_result

    result = st.session_state.get("tailor_result")
    if result:
        if not result.get("ok"):
            st.error(str(result.get("error", "Tailoring failed.")))
        else:
            st.success(f"Done using `{result.get('mode')}` mode.")
            if require_openai and str(result.get("mode", "")) != "openai":
                st.error("OpenAI rewrite was required, but app fell back. Check API key/billing/model access and retry.")
                notes = result.get("notes")
                if notes:
                    st.caption(str(notes))
            else:
                if str(result.get("mode", "")) != "openai":
                    st.warning("Heuristic mode used. Set OPENAI_API_KEY for stronger JD-specific rewriting.")

                summary = result.get("change_summary", [])
                if summary:
                    st.subheader("Change Summary")
                    for item in summary:
                        st.write(f"- {item}")

                notes = result.get("notes")
                if notes:
                    st.caption(str(notes))
                    if "PyMuPDF not installed" in str(notes):
                        st.warning("Install dependencies from requirements.txt to enable style-preserving PDF output.")

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
                    st.warning("Output format could not be preserved; exported with fallback format.")

    latex_result = st.session_state.get("latex_result")
    if latex_result:
        st.markdown("---")
        st.subheader("LaTeX Output (Template Format)")
        if not latex_result.get("ok"):
            st.error(str(latex_result.get("error", "LaTeX generation failed.")))
        else:
            st.success(f"LaTeX resume generated using `{latex_result.get('mode')}` mode.")
            if require_openai and str(latex_result.get("mode", "")) != "openai":
                st.error("OpenAI rewrite was required, but LaTeX generation fell back to heuristic extraction.")
            sections = latex_result.get("sections", {})
            if sections:
                st.caption(
                    "Extracted sections: "
                    + ", ".join(f"{k}={v}" for k, v in sections.items())
                )
            notes = latex_result.get("notes")
            if notes:
                st.caption(str(notes))

            tex_path = Path(str(latex_result.get("tex_path", "")))
            if tex_path.exists():
                st.download_button(
                    "Download LaTeX (.tex)",
                    data=tex_path.read_bytes(),
                    file_name=tex_path.name,
                    mime="text/x-tex",
                    use_container_width=True,
                    key="download_tex",
                )

            asset_paths = latex_result.get("asset_paths", {})
            cls_path = Path(str(asset_paths.get("resume.cls", ""))) if isinstance(asset_paths, dict) else Path()
            if cls_path and cls_path.exists():
                st.download_button(
                    "Download resume.cls",
                    data=cls_path.read_bytes(),
                    file_name=cls_path.name,
                    mime="text/plain",
                    use_container_width=True,
                    key="download_cls",
                )
    if not result and not latex_result:
        return


if __name__ == "__main__":
    main()
