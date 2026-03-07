from ingest.build_metadata import main as build_metadata_main
from ingest.extract_case_struct import main as extract_case_main


def main() -> None:
    print("[1/2] build metadata...")
    build_metadata_main(["--fast"])
    print("[2/2] extract structured cases...")
    extract_case_main()
    print("done.")


if __name__ == "__main__":
    main()
