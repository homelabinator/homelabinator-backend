
  {{ user_content }}

  programs.bash.loginShellInit = ''
    # Enable strict error checking and pipe failure detection
    set -e
    set -o pipefail
    
    # Error handler: If any command fails, print the details and drop to a shell
    handle_error() {
      local exit_code=$?
      local failed_command="$BASH_COMMAND"
      local line_number=$1
        
      echo ""
      echo "=========================================================="
      echo "ERROR: Script encountered a failure!"
      echo "Failed Command : $failed_command"
      echo "Line Number    : $line_number"
      echo "Exit Code      : $exit_code"
      echo "=========================================================="
      echo "Dropping to an interactive shell for troubleshooting..."
        
      # Replace the current process with an interactive bash shell
      exec bash
    }
    
    # Trap ERR (Errors) and execute the handle_error function
    trap 'handle_error $LINENO' ERR
    
    # Check if we are on tty1 and the user is correct 
    # (Note: Added a space to 'if [' so bash evaluates it properly)
    if [ "$(tty)" = "/dev/tty1" ] && [ "$USER" = "homelab" ]; then
        
      # Optional: Check if a graphical session is already running 
      # to prevent infinite loops if you drop to a terminal later
      if [ -z "$DISPLAY" ] && [ -z "$WAYLAND_DISPLAY" ]; then
          
        echo "Auto-login successful. Executing startup script..."
          
        # -------------------------------------------------------------------------
        # Section 1: Homelabinator Configuration injection
        # -------------------------------------------------------------------------
        if [ -f /etc/homelabinator-config ]; then
            
          CONFIG_NIX="/etc/nixos/configuration.nix"
            
          # Find the specific text line, and delete from that line to the end of the file ($d). 
          # This inherently removes the last '}' at the bottom of the file as well.
          sudo ${pkgs.gnused}/bin/sed -i "/environment\.etc\.\"homelabinator-config\"\.text = .*/,\$d" "$CONFIG_NIX"
            
          # Inject the entire contents of /etc/homelabinator-config to the bottom of the file
          sudo bash -c "${pkgs.coreutils}/bin/cat /etc/homelabinator-config >> $CONFIG_NIX"
            
          # Add back the '}' at the end of the file on a newline
          sudo bash -c "echo -e '\n}' >> $CONFIG_NIX"
            
          echo 'Installing Homelabinator'
            
          # Rebuild NixOS
          sudo nixos-rebuild switch
            
          echo 'Homelabinator Successfully installed! Happy Homelabbing!'
          echo 'Rebooting in 5 seconds...'
            
          sleep 5
          sudo reboot
            
        # -------------------------------------------------------------------------
        # Section 2: Standard Boot (Homelabinator already installed)
        # -------------------------------------------------------------------------
        else
          echo 'Welcome to Homelabinator!'
            
          echo 'Waiting for a local IP address...'
            
          LOCAL_IP=""
          # Loop until we successfully find a valid IP
          while [ -z "$LOCAL_IP" ]; do
            # Use iproute2 and awk to filter out lo, veth*, flannel*, cin0*, cni0* 
            # then grab the actual IP using cut and head
            LOCAL_IP=$(${pkgs.iproute2}/bin/ip -o -4 addr show up | \
                       ${pkgs.gawk}/bin/awk '$2 !~ /^(veth|flannel|cin|cni|lo)/ {print $4}' | \
                       ${pkgs.coreutils}/bin/cut -d/ -f1 | \
                       ${pkgs.coreutils}/bin/head -n 1)
              
            if [ -z "$LOCAL_IP" ]; then
              sleep 2
            fi
          done
            
          # Wait a brief moment to ensure cluster readiness after networking is up
          sleep 2
            
          NODE_IP=$(sudo k3s kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}')
    
          # 2. Get all NodePort services, extract their names and nodePorts, and format the output
          sudo k3s kubectl get svc -n default -o jsonpath='{range .items[?(@.spec.type=="NodePort")]}{.metadata.name}{" "}{range .spec.ports[*]}{.nodePort}{" "}{end}{"\n"}{end}' | \
          while read -r svc ports; do
            # Loop through ports (in case a single service exposes multiple NodePorts)
            for port in $ports; do
              printf "%s:\t http://%s:%s\n" "$svc" "$NODE_IP" "$port"
            done
          done
            
        fi
      fi
    fi
  '';
