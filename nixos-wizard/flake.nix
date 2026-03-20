{
  description = "Nixos TUI Installer (Wizard)";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs?ref=nixos-unstable";
    fenix = {
      url = "github:nix-community/fenix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { self, nixpkgs, fenix }@inputs:
  let
    system = "x86_64-linux";
    mkRustToolchain = fenix.packages.${system}.complete.withComponents;
    pkgs = import nixpkgs { inherit system; };
    nixosWizard = pkgs.rustPlatform.buildRustPackage {
      pname = "nixos-wizard";
      version = "0.3.2";

      src = self;

      cargoLock.lockFile = ./Cargo.lock;
    };
  in
  {
    packages.${system} = {
      default = nixosWizard;
      nixos-wizard = nixosWizard;
    };

    devShells.${system}.default = let
      toolchain = mkRustToolchain [
        "cargo"
        "clippy"
        "rustfmt"
        "rustc"
      ];
    in
      pkgs.mkShell {
        packages = [ toolchain pkgs.rust-analyzer ];

        shellHook = ''
          export SHELL=${pkgs.zsh}/bin/zsh
          exec ${pkgs.zsh}/bin/zsh
        '';
      };
  };
}
