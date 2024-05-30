{ isDevelopment ? true }:

let
  # Update packages with `nixpkgs-update` command
  pkgs = import (fetchTarball "https://github.com/NixOS/nixpkgs/archive/ac82a513e55582291805d6f09d35b6d8b60637a1.tar.gz") { };

  pythonLibs = with pkgs; [
    stdenv.cc.cc.lib
    zlib.out
  ];

  # Override LD_LIBRARY_PATH to load Python libraries
  wrappedPython = with pkgs; symlinkJoin {
    name = "python";
    paths = [ python312 ];
    buildInputs = [ makeWrapper ];
    postBuild = ''
      wrapProgram "$out/bin/python3.12" --prefix LD_LIBRARY_PATH : "${lib.makeLibraryPath pythonLibs}"
    '';
  };

  packages' = with pkgs; [
    wrappedPython
    poetry
    ruff
    inotify-tools

    (writeShellScriptBin "run-tests" ''
      set -e
      pytest . --cov starlette_compress --cov-report xml
      mypy .
    '')
    (writeShellScriptBin "watch-tests" ''
      run-tests || true
      while inotifywait -e close_write ./**/*.py; do
        run-tests || true
      done
    '')
    (writeShellScriptBin "nixpkgs-update" ''
      set -e
      hash=$(git ls-remote https://github.com/NixOS/nixpkgs nixpkgs-unstable | cut -f 1)
      sed -i -E "s|/nixpkgs/archive/[0-9a-f]{40}\.tar\.gz|/nixpkgs/archive/$hash.tar.gz|" shell.nix
      echo "Nixpkgs updated to $hash"
    '')
  ];

  shell' = with pkgs; lib.optionalString isDevelopment ''
    current_python=$(readlink -e .venv/bin/python || echo "")
    current_python=''${current_python%/bin/*}
    [ "$current_python" != "${wrappedPython}" ] && rm -r .venv

    echo "Installing Python dependencies"
    export POETRY_VIRTUALENVS_IN_PROJECT=1
    poetry env use "${wrappedPython}/bin/python"
    poetry install --compile

    echo "Activating Python virtual environment"
    source .venv/bin/activate

    # Development environment variables
    export PYTHONNOUSERSITE=1
    export TZ=UTC
  '';
in
pkgs.mkShell {
  buildInputs = packages';
  shellHook = shell';
}
