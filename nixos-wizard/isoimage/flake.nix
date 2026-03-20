{
  description = "NixOS ISO Image for Wizard";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs?ref=nixos-unstable";
    wizard.url = "github:homelabinator/homelabinator-backend?dir=nixos-wizard"; # Reference the root flake
  };

  outputs = { self, nixpkgs, wizard }@inputs:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};

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
          ];
        };
      };

      packages.${system} = {
        default = self.nixosConfigurations.installerIso.config.system.build.isoImage;
        iso = self.nixosConfigurations.installerIso.config.system.build.isoImage;
      };
    };
}
