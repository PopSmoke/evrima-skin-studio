"""Portable entry point; retain console errors instead of silently detaching."""
from pathlib import Path
import argparse, os, sys, traceback
ROOT=Path(__file__).resolve().parent
def launch():
    parser=argparse.ArgumentParser()
    parser.add_argument('--check-startup',type=Path,help=argparse.SUPPRESS)
    args=parser.parse_args()
    os.environ['TCL_LIBRARY']=str(ROOT/'runtime/tcl/tcl8.6')
    os.environ['TK_LIBRARY']=str(ROOT/'runtime/tcl/tk8.6')
    sys.path.insert(0,str(ROOT/'app/outputs/EvrimaSkinEditor'))
    documents=Path.home()/'Documents'
    os.chdir(documents if documents.is_dir() else Path.home())
    from skin_editor import main
    if args.check_startup is None:main()
    else:
        report=args.check_startup.resolve()
        if report.exists():raise ValueError('Startup test report already exists')
        main(startup_check=report)
        import json
        if not report.is_file() or not json.loads(report.read_text())['passed']:
            raise RuntimeError('Startup check did not produce a visible, rendered window')

if __name__=='__main__':
    try:launch()
    except Exception:
        details=traceback.format_exc()
        if sys.stderr is not None:print(details,file=sys.stderr,flush=True)
        try:
            folder=Path(os.environ.get('LOCALAPPDATA',str(ROOT)))/'EvrimaSkinStudio'
            folder.mkdir(parents=True,exist_ok=True)
            (folder/'startup-error.txt').write_text(details,encoding='utf-8')
        except OSError:pass
        raise SystemExit(1)
