$c = New-Object Net.Sockets.TcpClient
$c.Connect('127.0.0.1', 7778)
$c.Close()
