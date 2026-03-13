
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
          
          echo "Cleaning up Homelabinator first-time setup markers..."
          
          # Safely create a temporary file
          TMP_CONFIG=$(sudo ${pkgs.coreutils}/bin/mktemp)
          
          # We use awk to keep a rolling 1-line buffer. This allows us to easily drop
          # the line above the END marker. We use getline to drop the line below BEGIN.
          # Note: We use standard single quotes '...', avoiding Nix's double single quotes.
          sudo ${pkgs.gawk}/bin/awk '
          {
            if ($0 ~ /# \*\*\* BEGIN HOMELABINATOR FIRST TIME SETUP/) {
              if (has_prev) print prev_line
              getline
              has_prev = 0
              next
            }
            if ($0 ~ /# \*\*\* END HOMELABINATOR FIRST TIME SETUP/) {
              has_prev = 0
              next
            }
            if (has_prev) print prev_line
            prev_line = $0
            has_prev = 1
          }
          END {
            if (has_prev) print prev_line
          }' "$CONFIG_NIX" | sudo ${pkgs.coreutils}/bin/tee "$TMP_CONFIG" > /dev/null
          
          # Overwrite the original config and ensure correct file permissions
          sudo ${pkgs.coreutils}/bin/mv "$TMP_CONFIG" "$CONFIG_NIX"
          sudo ${pkgs.coreutils}/bin/chmod 644 "$CONFIG_NIX"
          
          echo "Installing Homelabinator..."
          
          # Rebuild NixOS
          sudo nixos-rebuild switch
          
          echo "Homelabinator Successfully installed! Happy Homelabbing!"
          echo "Rebooting in 5 seconds..."
          
          sleep 5
          sudo reboot
          
        # -------------------------------------------------------------------------
        # Section 2: Standard Boot (Homelabinator already installed)
        # -------------------------------------------------------------------------
        else
          echo "Welcome to Homelabinator!"
          
          echo "Waiting for a local IP address..."
          
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
