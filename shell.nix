{ newPython ? true }:

let
  # Update packages with `nixpkgs-update` command
  pkgs = import (fetchTarball "https://github.com/NixOS/nixpkgs/archive/804aa8f1795acfb4a38d552d557023796876c020.tar.gz") { };

  pythonLibs = with pkgs; [
    zlib.out
    stdenv.cc.cc.lib
  ];

  # Override LD_LIBRARY_PATH to load Python libraries
  python' = with pkgs; symlinkJoin {
    name = "python";
    paths = [ (if newPython then python314 else python313) ];
    buildInputs = [ makeWrapper ];
    postBuild = ''
      wrapProgram "$out/bin/python3.${if newPython then "14" else "13"}" --prefix LD_LIBRARY_PATH : "${lib.makeLibraryPath pythonLibs}"
    '';
  };

  packages' = with pkgs; [
    coreutils
    which
    file
    python'
    uv
    hatch
    ruff
    pyright
    watchexec
    libffi.dev
    libuv.dev

    (writeShellScriptBin "run-tests" ''
      set -e
      pyright
      set +e
      python -m coverage run -m pytest \
        --verbose \
        --no-header
      result=$?
      set -e
      if [ "$1" = "term" ]; then
        python -m coverage report --skip-covered
      else
        python -m coverage xml --quiet
      fi
      python -m coverage erase
      exit $result
    '')
    (writeShellScriptBin "watch-tests" "watchexec --watch starlette_compress --watch tests --exts py run-tests")
    (writeShellScriptBin "nixpkgs-update" ''
      set -e
      hash=$(
        curl --silent --location \
        https://prometheus.nixos.org/api/v1/query \
        -d "query=channel_revision{channel=\"nixpkgs-unstable\"}" | \
        grep --only-matching --extended-regexp "[0-9a-f]{40}")
      sed -i -E "s|/nixpkgs/archive/[0-9a-f]{40}\.tar\.gz|/nixpkgs/archive/$hash.tar.gz|" shell.nix
      echo "Nixpkgs updated to $hash"
    '')
  ];

  shell' = ''
    export TZ=UTC
    export NIX_ENFORCE_PURITY=0
    export PYTHONNOUSERSITE=1
    export PYTHONPATH=""
    export COVERAGE_CORE=sysmon

    current_python=$(readlink -e .venv/bin/python || echo "")
    current_python=''${current_python%/bin/*}
    [ "$current_python" != "${python'}" ] && rm -rf .venv/

    echo "Installing Python dependencies"
    export UV_PYTHON="${python'}/bin/python"
    uv sync --frozen

    echo "Activating Python virtual environment"
    source .venv/bin/activate
  '';
in
pkgs.mkShell {
  buildInputs = packages';
  shellHook = shell';
}
