"""Owner-operated development server. Public deployment uses static assets only."""
from __future__ import annotations
import argparse
import os
from pathlib import Path

def main():
    import uvicorn
    from .api import create_app
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,default=Path(".state/live"))
    parser.add_argument("--port",type=int,default=8097)
    args=parser.parse_args()
    token=os.environ.get("SWE_WORKBENCH_OWNER_TOKEN")
    if not token or len(token)<32 or not token.isascii():
        parser.error("Set SWE_WORKBENCH_OWNER_TOKEN to at least 32 high-entropy ASCII characters.")
    app=create_app(args.root,owner_token=token)
    uvicorn.run(app,host="127.0.0.1",port=args.port,log_level="warning",proxy_headers=False)

if __name__=="__main__":
    main()

