{ isDevelopment ? true }:

let
  # Update packages with `nixpkgs-update` command
  pkgs = import (fetchTarball "https://github.com/NixOS/nixpkgs/archive/2d2a9ddbe3f2c00747398f3dc9b05f7f2ebb0f53.tar.gz") { };

  pythonLibs = with pkgs; [
    stdenv.cc.cc.lib
    zlib.out
  ];

  # Override LD_LIBRARY_PATH to load Python libraries
  python' = with pkgs; symlinkJoin {
    name = "python";
    paths = [ python313 ];
    buildInputs = [ makeWrapper ];
    postBuild = ''
      wrapProgram "$out/bin/python3.13" --prefix LD_LIBRARY_PATH : "${lib.makeLibraryPath pythonLibs}"
    '';
  };

  packages' = with pkgs; [
    coreutils
    python'
    poetry
    ruff
    pyright
    watchexec

    (writeShellScriptBin "run-tests" ''
      set -e
      python -m pytest . \
        --verbose \
        --no-header \
        --cov starlette_compress \
        --cov-report "''${1:-xml}"
      pyright
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

  shell' = with pkgs; lib.optionalString isDevelopment ''
    export PYTHONNOUSERSITE=1
    export TZ=UTC

    current_python=$(readlink -e .venv/bin/python || echo "")
    current_python=''${current_python%/bin/*}
    [ "$current_python" != "${python'}" ] && rm -rf .venv/

    echo "Installing Python dependencies"
    export POETRY_VIRTUALENVS_IN_PROJECT=1
    poetry env use "${python'}/bin/python"
    poetry install --compile

    echo "Activating Python virtual environment"
    source .venv/bin/activate
  '';
in
pkgs.mkShell {
  buildInputs = packages';
  shellHook = shell';
}
