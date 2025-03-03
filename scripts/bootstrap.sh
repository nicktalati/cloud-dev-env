#!/bin/bash -xe

apt-get update -y

DEBIAN_FRONTEND=noninteractive apt-get install -y \
  git curl build-essential libssl-dev zlib1g-dev \
  libbz2-dev libreadline-dev libsqlite3-dev libncursesw5-dev xz-utils \
  tk-dev libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev tree ripgrep \
  tmux zsh fzf

chsh -s /usr/bin/zsh ubuntu

echo 'export ZDOTDIR="$HOME/.config/zsh"' >> /etc/zsh/zshenv

curl -LO https://github.com/neovim/neovim/releases/latest/download/nvim-linux-x86_64.tar.gz
rm -rf /opt/nvim
tar -C /opt -xzf nvim-linux-x86_64.tar.gz

sudo -u ubuntu bash <<'EOF'
set -xe

echo 'export PATH="$PATH:/opt/nvim-linux-x86_64/bin"' >> $HOME/.config/.zshenv

aws ssm get-parameter --region us-east-1 --name "id_rsa_aws" --with-decryption --query "Parameter.Value" --output text > $HOME/.ssh/id_rsa
chmod 600 $HOME/.ssh/id_rsa

git clone git@github.com:nicktalati/dotfiles.git $HOME/dotfiles

mkdir -p $HOME/.config
ln -sf $HOME/dotfiles/zsh $HOME/.config/zsh
ln -sf $HOME/dotfiles/tmux $HOME/.config/tmux
ln -sf $HOME/dotfiles/nvim $HOME/.config/nvim

curl -fsSL https://pyenv.run | bash
EOF

echo "Bootstrap complete!"
