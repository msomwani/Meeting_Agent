import time
import os
from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END

from schemas.state import MeetingState
from agents.cleaner import clean_transcript
from agents.summariser import summarise_meeting
from agents.extractor import extract_action_items
from agents.decisions import extract_decisions
from agents.reporter import assemble_report

load_dotenv()


def build_graph() -> StateGraph:
    """
    Constructs and compiles the LangGraph StateGraph.
    Called once at module load — reuse the compiled graph for all runs.
    """
    graph = StateGraph(MeetingState)

    graph.add_node("cleaner",    clean_transcript)
    graph.add_node("summariser", summarise_meeting)
    graph.add_node("extractor",  extract_action_items)
    graph.add_node("decisions",  extract_decisions)
    graph.add_node("reporter",   assemble_report)

    # Sequential: START → cleaner → summariser
    graph.add_edge(START,       "cleaner")
    graph.add_edge("cleaner",   "summariser")

    # Parallel branch: summariser fans out to both extractor AND decisions
    graph.add_edge("summariser", "extractor")
    graph.add_edge("summariser", "decisions")

    # Fan back in: both parallel nodes must complete before reporter runs
    graph.add_edge("extractor",  "reporter")
    graph.add_edge("decisions",  "reporter")

    # Final: reporter → END
    graph.add_edge("reporter",   END)

    return graph.compile()


# Compile once at import time
pipeline = build_graph()


def _get_langfuse_handler():
    """
    Returns a Langfuse CallbackHandler if credentials are configured,
    otherwise returns None so the pipeline still runs without observability.
    """
    public_key  = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key  = os.getenv("LANGFUSE_SECRET_KEY")
    host        = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

    if not public_key or not secret_key:
        print("Langfuse: no credentials found — running without observability.")
        print("  Add LANGFUSE_PUBLIC_KEY + LANGFUSE_SECRET_KEY to .env to enable.")
        return None

    try:
        from langfuse.callback import CallbackHandler
        handler = CallbackHandler(
            public_key=public_key,
            secret_key=secret_key,
            host=host,
        )
        print("Langfuse: callback handler initialised.")
        return handler
    except ImportError:
        print("Langfuse: package not installed — pip install langfuse")
        return None


def run_pipeline(state: MeetingState) -> MeetingState:
    """
    Runs the full 5-node agent pipeline on a populated MeetingState.

    Returns the same state dict with all fields populated including
    state["final_report"] as a MeetingReport object.
    """
    print("\n" + "="*50)
    print("Starting MeetMind agent pipeline")
    print("="*50)

    pipeline_start = time.time()

    langfuse_handler = _get_langfuse_handler()

    config = {}
    if langfuse_handler:
        config["callbacks"] = [langfuse_handler]

    result = pipeline.invoke(state, config=config)

    pipeline_duration = round(time.time() - pipeline_start, 1)

    if result.get("final_report"):
        result["final_report"].pipeline_duration_seconds = pipeline_duration

    print("\n" + "="*50)
    print(f"Pipeline complete in {pipeline_duration}s")
    if result.get("final_report"):
        r = result["final_report"]
        print(f"  Meeting ID   : {r.meeting_id}")
        print(f"  Speakers     : {r.num_speakers}")
        print(f"  Action items : {len(r.action_items)}")
        print(f"  Decisions    : {len(r.decision)}")
    print("="*50 + "\n")

    return result