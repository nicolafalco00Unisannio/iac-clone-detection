"""
CLI entry point for clone detection.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
import time
import logging
import json
import os

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def _build_clone_groups(clone_pairs):
    import networkx as nx

    if not clone_pairs:
        return []
    graph = nx.Graph([(p1, p2) for p1, p2, _ in clone_pairs])
    return list(nx.connected_components(graph))


def _load_checkpoint(checkpoint_path: Path):
    if not checkpoint_path.exists():
        return None
    try:
        return json.loads(checkpoint_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as e:
        logging.warning("Could not read checkpoint %s: %s", checkpoint_path, e)
        return None


def _to_json_compatible(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _to_json_compatible(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_json_compatible(v) for v in value]
    if isinstance(value, set):
        return sorted(_to_json_compatible(v) for v in value)
    return value


def _persist_checkpoint_payload(checkpoint_path: Path, payload) -> None:
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_text = json.dumps(_to_json_compatible(payload), indent=2)
    last_error = None

    # Atomic write: write to .tmp then replace, so the file won't corrupt if the process dies
    for attempt in range(5):
        tmp_path = checkpoint_path.with_name(
            f"{checkpoint_path.name}.{os.getpid()}.{time.time_ns()}.tmp"
        )
        try:
            with tmp_path.open('w', encoding='utf-8') as handle:
                handle.write(checkpoint_text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, checkpoint_path)
            return
        except PermissionError as e:
            last_error = e
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            time.sleep(0.1 * (attempt + 1))
        except OSError as e:
            last_error = e
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            break

    recovery_path = checkpoint_path.with_name(f"{checkpoint_path.stem}_recovery{checkpoint_path.suffix}")
    try:
        recovery_path.write_text(checkpoint_text, encoding='utf-8')
        logging.warning(
            "Checkpoint lock on %s; wrote recovery checkpoint to %s instead.",
            checkpoint_path,
            recovery_path,
        )
    except OSError as recovery_error:
        logging.warning(
            "Could not persist checkpoint to %s or recovery file %s: %s / %s",
            checkpoint_path,
            recovery_path,
            last_error,
            recovery_error,
        )


def _save_checkpoint(
    checkpoint_path: Path,
    root_dir: str,
    output: str,
    total_projects: int,
    processed_projects,
    clone_pairs,
    skipped_projects: int,
    skipped_timeouts: int,
    skipped_errors: int,
    status: str,
    current_project_state=None,
):
    payload = {
        "root_dir": root_dir,
        "output": output,
        "total_projects": total_projects,
        "processed_projects": sorted(processed_projects),
        "clone_pairs": [[str(p1), str(p2), dist] for p1, p2, dist in clone_pairs],
        "skipped_projects": skipped_projects,
        "skipped_timeouts": skipped_timeouts,
        "skipped_errors": skipped_errors,
        "status": status,
        "current_project_state": current_project_state,
        "saved_at": time.strftime('%Y-%m-%d %H:%M:%S'),
    }
    _persist_checkpoint_payload(checkpoint_path, payload)


def _partial_report_name(output_filename: str) -> str:
    out = Path(output_filename)
    suffix = out.suffix or '.html'
    return str(out.with_name(f"{out.stem}_partial{suffix}"))


def _write_minimal_summary_report(
    output_filename: str,
    processed_count: int,
    total_projects: int,
    skipped_projects: int,
    skipped_timeouts: int,
    skipped_errors: int,
    interrupted: bool,
):
    status = "Interrupted" if interrupted else "Completed"
    html = f"""<!DOCTYPE html>
<html><head><meta charset=\"UTF-8\"><title>Clone Detection Summary</title></head>
<body style=\"font-family:Segoe UI,Tahoma,sans-serif;max-width:900px;margin:2rem auto;padding:1rem;\">
<h1>Clone Detection Summary</h1>
<p><strong>Status:</strong> {status}</p>
<p><strong>Processed projects:</strong> {processed_count}/{total_projects}</p>
<p><strong>Skipped:</strong> {skipped_projects} (timeouts: {skipped_timeouts}, errors: {skipped_errors})</p>
<p>No clone pairs were available for detailed report generation.</p>
</body></html>
"""
    Path(output_filename).write_text(html, encoding='utf-8')


def _merge_clone_pairs(base_pairs, current_project_state):
    merged = [(Path(p1), Path(p2), dist) for p1, p2, dist in base_pairs]
    if not current_project_state:
        return merged
    partial_pairs = current_project_state.get("clone_pairs", [])
    merged.extend((Path(item[0]), Path(item[1]), item[2]) for item in partial_pairs if len(item) == 3)
    return merged

def main():
    from src.detectors.zss_detector import detect_clones_smart
    from src.visualization.report_generator import generate_comprehensive_report

    parser = argparse.ArgumentParser(description='IaC Clone Detector')
    parser.add_argument('--root_dir', default='C:/Users/Falco/Documents/Università/EQS/Materiale/TerraDS', help='Root directory to scan')
    parser.add_argument('--limit', type=int, default=1000, help='Max files to process')
    parser.add_argument('--threshold', type=int, default=5, help='Distance threshold')
    parser.add_argument('--output', default='clone_report.html', help='Output report filename')
    parser.add_argument('--per_project', action='store_true', help='Analyze each immediate subdirectory as a project and aggregate into one report')
    parser.add_argument('--project_limit', type=int, default=None, help='Max number of projects to analyze when using --per_project')
    parser.add_argument('--project_timeout', type=int, default=600, help='Per-project timeout in seconds (default: 600)')
    parser.add_argument('--checkpoint_file', default='clone_checkpoint.json', help='Checkpoint file for progress and partial results')
    parser.add_argument('--resume_checkpoint', action='store_true', help='Resume per-project analysis from an existing checkpoint file')
    parser.add_argument('--checkpoint_interval', type=int, default=300, help='Seconds between timed checkpoints within a project')
    
    args = parser.parse_args()
    
    if args.per_project:
        root = Path(args.root_dir)
        project_dirs = sorted([p for p in root.iterdir() if p.is_dir()], key=lambda p: p.name.lower())
        if args.project_limit:
            project_dirs = project_dirs[:args.project_limit]
        
        total_projects = len(project_dirs)
        logging.info("Starting analysis on %s projects.", total_projects)
        
        checkpoint_path = Path(args.checkpoint_file)
        all_clone_pairs = []
        processed_projects = set()
        skipped_projects = 0
        skipped_timeouts = 0
        skipped_errors = 0
        interrupted = False
        current_project_state = None
        initial_processed_count = 0
        initial_skipped_projects = 0
        initial_skipped_timeouts = 0
        initial_skipped_errors = 0

        if args.resume_checkpoint:
            checkpoint = _load_checkpoint(checkpoint_path)
            if checkpoint:
                restored_pairs = checkpoint.get("clone_pairs", [])
                all_clone_pairs = [(Path(item[0]), Path(item[1]), item[2]) for item in restored_pairs if len(item) == 3]
                processed_projects = set(checkpoint.get("processed_projects", []))
                skipped_projects = int(checkpoint.get("skipped_projects", 0))
                skipped_timeouts = int(checkpoint.get("skipped_timeouts", 0))
                skipped_errors = int(checkpoint.get("skipped_errors", 0))
                current_project_state = checkpoint.get("current_project_state")
                logging.info(
                    "Resumed checkpoint %s: %s projects already processed, %s clone pairs restored.",
                    checkpoint_path,
                    len(processed_projects),
                    len(all_clone_pairs),
                )
                if current_project_state:
                    logging.info(
                        "Discarding partial state for %s and reprocessing that project.",
                        current_project_state.get('project_name'),
                    )
                    current_project_state = None

        initial_processed_count = len(processed_projects)
        initial_skipped_projects = skipped_projects
        initial_skipped_timeouts = skipped_timeouts
        initial_skipped_errors = skipped_errors
        
        start_time = time.time()

        remaining_projects = [p for p in project_dirs if p.name not in processed_projects]
        already_done = total_projects - len(remaining_projects)

        try:
            for i, project_dir in enumerate(remaining_projects, already_done + 1):
                logging.info("[%s/%s] Analyzing: %s...", i, total_projects, project_dir.name)
                current_project_state = {
                    "project_name": project_dir.name,
                    "phase": "starting",
                    "files_total": 0,
                    "files_processed": 0,
                    "skipped_files": 0,
                    "total_comparisons": 0,
                    "comparisons_completed": 0,
                    "clone_pairs": [],
                }

                def on_project_progress(progress, project_name=project_dir.name):
                    nonlocal current_project_state
                    current_project_state = {
                        "project_name": project_name,
                        "phase": progress.get("phase", "unknown"),
                        "files_total": progress.get("files_total", 0),
                        "files_processed": progress.get("files_processed", 0),
                        "skipped_files": progress.get("skipped_files", 0),
                        "bucket_count": progress.get("bucket_count", 0),
                        "total_comparisons": progress.get("total_comparisons", 0),
                        "comparisons_completed": progress.get("comparisons_completed", 0),
                        "clone_pairs": [[p1, p2, dist] for p1, p2, dist in progress.get("clone_pairs", [])],
                    }
                    _save_checkpoint(
                        checkpoint_path=checkpoint_path,
                        root_dir=args.root_dir,
                        output=args.output,
                        total_projects=total_projects,
                        processed_projects=processed_projects,
                        clone_pairs=all_clone_pairs,
                        skipped_projects=skipped_projects,
                        skipped_timeouts=skipped_timeouts,
                        skipped_errors=skipped_errors,
                        status='running',
                        current_project_state=current_project_state,
                    )

                try:
                    clone_pairs = detect_clones_smart(
                        str(project_dir),
                        args.limit,
                        args.threshold,
                        timeout_seconds=args.project_timeout,
                        progress_callback=on_project_progress,
                        checkpoint_interval_seconds=args.checkpoint_interval,
                    )
                except TimeoutError:
                    skipped_projects += 1
                    skipped_timeouts += 1
                    logging.warning("   -> Skipped %s (timeout: %ss)", project_dir.name, args.project_timeout)
                    clone_pairs = []
                except (OSError, ValueError, RuntimeError) as e:
                    skipped_projects += 1
                    skipped_errors += 1
                    logging.warning("   -> Skipped %s (error: %s)", project_dir.name, e)
                    clone_pairs = []

                if clone_pairs:
                    all_clone_pairs.extend(clone_pairs)
                    logging.info("   -> Found %s clones in %s", len(clone_pairs), project_dir.name)

                processed_projects.add(project_dir.name)
                current_project_state = None
                _save_checkpoint(
                    checkpoint_path=checkpoint_path,
                    root_dir=args.root_dir,
                    output=args.output,
                    total_projects=total_projects,
                    processed_projects=processed_projects,
                    clone_pairs=all_clone_pairs,
                    skipped_projects=skipped_projects,
                    skipped_timeouts=skipped_timeouts,
                    skipped_errors=skipped_errors,
                    status='running',
                    current_project_state=current_project_state,
                )

                elapsed = time.time() - start_time
                avg_time = elapsed / i if i else 0
                eta = (total_projects - i) * avg_time
                logging.info("   -> Elapsed: %.1fs | ETA: %.1fs", elapsed, eta)
        except KeyboardInterrupt:
            interrupted = True
            logging.warning("Interruption detected. Saving checkpoint and generating partial report...")
        
        processed_this_run = len(processed_projects) - initial_processed_count
        skipped_this_run = skipped_projects - initial_skipped_projects
        timeouts_this_run = skipped_timeouts - initial_skipped_timeouts
        errors_this_run = skipped_errors - initial_skipped_errors
        analyzed_this_run = processed_this_run - skipped_this_run

        overall_processed = len(processed_projects)
        overall_analyzed = overall_processed - skipped_projects
        report_output = _partial_report_name(args.output) if interrupted else args.output
        report_clone_pairs = _merge_clone_pairs(all_clone_pairs, current_project_state)
        all_clone_groups = _build_clone_groups(report_clone_pairs)

        logging.info(
            "Analysis complete. This run analyzed: %s/%s remaining, skipped: %s (timeouts: %s, errors: %s). "
            "Overall progress analyzed: %s/%s, skipped: %s. Generating report for %s total pairs...",
            analyzed_this_run,
            len(remaining_projects),
            skipped_this_run,
            timeouts_this_run,
            errors_this_run,
            overall_analyzed,
            total_projects,
            skipped_projects,
            len(report_clone_pairs),
        )
        try:
            if report_clone_pairs or all_clone_groups:
                generate_comprehensive_report(report_clone_pairs, all_clone_groups, report_output)
            else:
                _write_minimal_summary_report(
                    output_filename=report_output,
                    processed_count=len(processed_projects),
                    total_projects=total_projects,
                    skipped_projects=skipped_projects,
                    skipped_timeouts=skipped_timeouts,
                    skipped_errors=skipped_errors,
                    interrupted=interrupted,
                )
                logging.info("Summary report generated: %s", report_output)
        except KeyboardInterrupt:
            interrupted = True
            report_output = _partial_report_name(args.output)
            logging.warning("Report generation interrupted. Writing fast summary to %s", report_output)
            _write_minimal_summary_report(
                output_filename=report_output,
                processed_count=len(processed_projects),
                total_projects=total_projects,
                skipped_projects=skipped_projects,
                skipped_timeouts=skipped_timeouts,
                skipped_errors=skipped_errors,
                interrupted=True,
            )
            logging.info("Fallback summary report generated: %s", report_output)

        _save_checkpoint(
            checkpoint_path=checkpoint_path,
            root_dir=args.root_dir,
            output=report_output,
            total_projects=total_projects,
            processed_projects=processed_projects,
            clone_pairs=all_clone_pairs,
            skipped_projects=skipped_projects,
            skipped_timeouts=skipped_timeouts,
            skipped_errors=skipped_errors,
            status='interrupted' if interrupted else 'completed',
            current_project_state=current_project_state,
        )

        if interrupted:
            logging.info("Partial report generated: %s", report_output)
            logging.info("Resume with: --per_project --resume_checkpoint --checkpoint_file %s", checkpoint_path)
    else:
        clone_pairs = detect_clones_smart(args.root_dir, args.limit, args.threshold)
        clone_groups = _build_clone_groups(clone_pairs)
        try:
            generate_comprehensive_report(clone_pairs, clone_groups, args.output)
        except KeyboardInterrupt:
            fallback_output = _partial_report_name(args.output)
            logging.warning("Report generation interrupted. Writing fast summary to %s", fallback_output)
            _write_minimal_summary_report(
                output_filename=fallback_output,
                processed_count=0,
                total_projects=1,
                skipped_projects=0,
                skipped_timeouts=0,
                skipped_errors=0,
                interrupted=True,
            )
            logging.info("Fallback summary report generated: %s", fallback_output)

if __name__ == "__main__":
    main()