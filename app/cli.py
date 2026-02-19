import argparse
import json
from pathlib import Path
from typing import List

from .ingest import build_index
from .memory import decide_memory, write_memory
from .qa import generate_answer
from .retrieval import retrieve
from .feature_c import run_weather_analysis


def cmd_ingest(args: argparse.Namespace) -> None:
    print(json.dumps(build_index(input_dir=args.input, data_dir=args.data_dir), indent=2))


def cmd_ask(args: argparse.Namespace) -> None:
    results = retrieve(args.question, top_k=args.top_k, data_dir=args.data_dir)
    answer, citations, mode = generate_answer(args.question, results)
    print(json.dumps({"question": args.question, "answer": answer, "mode": mode, "citations": citations}, indent=2))


def cmd_remember(args: argparse.Namespace) -> None:
    decision = decide_memory(args.text)
    write_result = write_memory(decision)
    print(
        json.dumps(
            {
                "should_write": decision.should_write,
                "target": decision.target,
                "summary": decision.summary,
                "confidence": decision.confidence,
                "write_result": write_result,
            },
            indent=2,
        )
    )


def cmd_sanity(_args: argparse.Namespace) -> None:
    build_index(input_dir="sample_docs", data_dir="data")
    questions = ["What is the main contribution?", "What limitation does the document mention?"]
    qa_items = []
    for q in questions:
        results = retrieve(q, top_k=1, data_dir="data")
        answer, citations, _mode = generate_answer(q, results)
        qa_items.append({"question": q, "answer": answer, "citations": citations})

    memory_inputs = [
        "I'm a Project Finance Analyst.",
        "Our recurring workflow bottleneck is delayed approvals between asset management and project finance.",
        "I prefer weekly summaries on Mondays.",
    ]
    memory_writes: List[dict] = []
    for text in memory_inputs:
        decision = decide_memory(text)
        result = write_memory(decision)
        if decision.should_write and result.get("summary"):
            memory_writes.append({"target": decision.target, "summary": result["summary"]})

    weather_demo = {}
    try:
        weather_demo = run_weather_analysis(
            location="New York",
            start_date="2025-01-01",
            end_date="2025-01-03",
            hourly_var="temperature_2m",
        )
    except Exception as e:
        weather_demo = {"error": str(e)}

    out = {
        "implemented_features": ["A", "B", "C"],
        "qa": qa_items,
        "demo": {"ingested_dir": "sample_docs", "memory_writes": memory_writes, "weather_analysis": weather_demo},
    }
    out_path = Path("artifacts/sanity_output.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps({"status": "ok", "output": out_path.as_posix()}, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Agentic RAG CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="Ingest docs and build index")
    p_ingest.add_argument("--input", default="sample_docs")
    p_ingest.add_argument("--data-dir", default="data")
    p_ingest.set_defaults(func=cmd_ingest)

    p_ask = sub.add_parser("ask", help="Ask grounded question")
    p_ask.add_argument("--question", required=True)
    p_ask.add_argument("--top-k", type=int, default=1)
    p_ask.add_argument("--data-dir", default="data")
    p_ask.set_defaults(func=cmd_ask)

    p_remember = sub.add_parser("remember", help="Write selective memory")
    p_remember.add_argument("--text", required=True)
    p_remember.set_defaults(func=cmd_remember)

    p_sanity = sub.add_parser("sanity", help="Generate sanity artifact")
    p_sanity.set_defaults(func=cmd_sanity)

    p_weather = sub.add_parser("weather-analyze", help="Feature C: safe weather time-series analysis via Open-Meteo")
    p_weather.add_argument("--location", required=True, help="Location name, e.g. 'New York'")
    p_weather.add_argument("--start-date", required=True, help="YYYY-MM-DD")
    p_weather.add_argument("--end-date", required=True, help="YYYY-MM-DD")
    p_weather.add_argument(
        "--hourly-var",
        default="temperature_2m",
        choices=["temperature_2m", "relative_humidity_2m", "precipitation", "wind_speed_10m", "surface_pressure"],
    )
    p_weather.set_defaults(func=cmd_weather_analyze)
    return parser


def cmd_weather_analyze(args: argparse.Namespace) -> None:
    result = run_weather_analysis(
        location=args.location,
        start_date=args.start_date,
        end_date=args.end_date,
        hourly_var=args.hourly_var,
    )
    print(json.dumps(result, indent=2))


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
