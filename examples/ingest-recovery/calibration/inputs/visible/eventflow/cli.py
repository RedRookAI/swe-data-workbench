import argparse
import json
from .state import State
from .pipeline import process

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("--state", required=True)
    args = parser.parse_args()
    state = State(args.state)
    try:
        with open(args.source, encoding="utf-8") as stream:
            print(json.dumps(process((json.loads(line) for line in stream), state)))
    finally:
        state.close()

if __name__ == "__main__":
    main()
