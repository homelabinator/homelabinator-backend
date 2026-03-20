{
  description = "NixOS ISO Image for Wizard";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs?ref=nixos-unstable";
    wizard.url = "path:.."; # Reference the root flake
    disko = {
      url = "github:nix-community/disko/latest";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { self, nixpkgs, wizard, disko }@inputs:
  let
    system = "x86_64-linux";
    pkgs = nixpkgs.legacyPackages.${system};
    diskoPkg = disko.packages.${system}.disko;
    
    # Dependencies that were previously in postInstall wrapper of the Rust program
    wizardDeps = [
      diskoPkg
      pkgs.bat
      pkgs.nixfmt-rfc-style
      pkgs.nixfmt-classic
      pkgs.util-linux
      pkgs.gawk
      pkgs.gnugrep
      pkgs.gnused
      pkgs.ntfs3g
    ];

    nixosWizard = wizard.packages.${system}.default;
  in
  {
    nixosConfigurations = {
      installerIso = nixpkgs.lib.nixosSystem {
        inherit system;
        specialArgs = {
          inherit inputs;
          nixosWizard = nixosWizard;
        };
        modules = [
          ./config.nix
          ({ pkgs, ... }: {
            environment.systemPackages = wizardDeps;
          })
        ];
      };
    };

    packages.${system} = {
      default = self.nixosConfigurations.installerIso.config.system.build.isoImage;
      iso = self.nixosConfigurations.installerIso.config.system.build.isoImage;
    };
  };
}
