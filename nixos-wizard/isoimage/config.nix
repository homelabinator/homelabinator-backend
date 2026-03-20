{ pkgs, modulesPath, nixosWizard, ... }: {
  imports = [
    "${modulesPath}/installer/cd-dvd/installation-cd-minimal.nix"
  ];

  environment.etc."issue".text = ''
    _   _                      _       _     _             _             
    | | | | ___  _ __ ___   ___| | __ _| |__ (_)_ __   __ _| |_ ___  _ __ 
    | |_| |/ _ \| '_ ` _ \ / _ \ |/ _` | '_ \| | '_ \ / _` | __/ _ \| '__|
    |  _  | (_) | | | | | |  __/ | (_| | |_) | | | | | (_| | || (_) | |   
    |_| |_|\___/|_| |_| |_|\___|_|\__,_|_.__/|_|_| |_|\__,_|\__\___/|_|   
                                                                          

    To set up a wireless connection, run `\e[1;35mnmtui\e[0m`.

    Run `\e[1;35msudo nixos-wizard\e[0m` to enter the installer.
  '';

  # isoImage.squashfsCompression = "gzip -Xcompression-level 1";
  isoImage.squashfsCompression = "zstd -Xcompression-level 1";
  isoImage.contents = [
    {
      source = ./homelabinator-init-script-template.nix;
      target = "/homelabinator-init-script.nix"; # Path on the generated ISO
    }
  ];

  environment.systemPackages = [
    nixosWizard
  ];

  nix.settings.experimental-features = [ "nix-command" "flakes" ];

  nixpkgs.hostPlatform = "x86_64-linux";
  networking.networkmanager.enable = true;
}
